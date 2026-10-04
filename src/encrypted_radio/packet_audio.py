"""Voice-band packet audio: 1200 bit/s continuous-phase AFSK.

The receiver acquires packets from PCM alone. Extended Hamming(8,4) coding,
bit-plane interleaving and CRC32 protect each independently acquired packet;
these transport checks are not authentication. No radio hardware is assumed.
"""

from collections import deque
from dataclasses import dataclass
import math
import secrets
import struct
import wave
import zlib

import numpy as np
from scipy import signal

from .audio import AudioError, iter_wav
from .morse import PROFILES, normalize_character

BAUD = 1200
MARK = 1200
SPACE = 2200
MAX_PAYLOAD = 256
# 64-bit sync has a low accidental-match probability, before header/FEC checks.
SYNC = np.unpackbits(np.frombuffer(bytes.fromhex("d391da26c5a74e18"), dtype=np.uint8))
TRAINING = np.tile(np.array([0, 1], dtype=np.uint8), 48)
HEADER = struct.Struct("!2sBB8sIH")
HEADER_BYTES = HEADER.size + 4
HEADER_BITS = HEADER_BYTES * 16
MAX_PACKET_BITS = HEADER_BITS + (MAX_PAYLOAD + 4) * 16
_CLOCKS = (1.0,) + tuple(1 + sign * step / 1_000_000 for step in range(125, 1001, 125) for sign in (-1, 1))


@dataclass(frozen=True)
class AFSKSettings:
    sample_rate: int = 48000
    baud: int = BAUD
    mark: int = MARK
    space: int = SPACE
    packet_size: int = 128
    lead_ms: float = 200.0
    tail_ms: float = 50.0

    def __post_init__(self):
        if not isinstance(self.sample_rate, int) or not 8000 <= self.sample_rate <= 192000:
            raise ValueError("sample rate must be an integer from 8000 to 192000 Hz")
        if (self.baud, self.mark, self.space) != (BAUD, MARK, SPACE):
            raise ValueError("audiolink v1 requires 1200 baud and 1200/2200 Hz tones")
        if not isinstance(self.packet_size, int) or not 1 <= self.packet_size <= MAX_PAYLOAD:
            raise ValueError("packet size must be between 1 and 256 ASCII bytes")
        for name, value, maximum in (("lead", self.lead_ms, 2000), ("tail", self.tail_ms, 2000)):
            if not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError(f"{name} guard must be between 0 and {maximum} ms")


# Extended Hamming parity positions 1,2,4; overall parity at position 8.
_CODEWORDS = np.zeros((16, 8), dtype=np.uint8)
for _n in range(16):
    _word = _CODEWORDS[_n]
    _word[[2, 4, 5, 6]] = [(_n >> shift) & 1 for shift in (3, 2, 1, 0)]
    _word[0] = _word[2] ^ _word[4] ^ _word[6]
    _word[1] = _word[2] ^ _word[5] ^ _word[6]
    _word[3] = _word[4] ^ _word[5] ^ _word[6]
    _word[7] = np.bitwise_xor.reduce(_word[:7])


def _fec_encode(data):
    values = np.frombuffer(data, dtype=np.uint8)
    nibbles = np.column_stack((values >> 4, values & 15)).reshape(-1)
    # Spread adjacent channel errors across different codewords.
    return _CODEWORDS[nibbles].T.reshape(-1)


def _fec_decode(bits):
    if len(bits) % 16:
        raise ValueError("invalid coded byte length")
    words = np.asarray(bits, dtype=np.uint8).reshape(8, -1).T.copy()
    syndrome = (words[:, 0] ^ words[:, 2] ^ words[:, 4] ^ words[:, 6])
    syndrome |= (words[:, 1] ^ words[:, 2] ^ words[:, 5] ^ words[:, 6]) << 1
    syndrome |= (words[:, 3] ^ words[:, 4] ^ words[:, 5] ^ words[:, 6]) << 2
    odd = np.bitwise_xor.reduce(words, axis=1)
    if np.any((syndrome != 0) & (odd == 0)):
        raise ValueError("uncorrectable Hamming codeword")
    rows = np.flatnonzero(odd)
    columns = np.where(syndrome[rows] == 0, 7, syndrome[rows] - 1)
    words[rows, columns] ^= 1
    nibbles = (words[:, 2] << 3) | (words[:, 4] << 2) | (words[:, 5] << 1) | words[:, 6]
    return bytes((nibbles[::2] << 4) | nibbles[1::2])


def _crc(data):
    return struct.pack("!I", zlib.crc32(data))


def _header(session, sequence, length, end=False):
    plain = HEADER.pack(b"AL", 1, int(end), session, sequence, length)
    return plain + _crc(plain)


class AFSKEncoder:
    """Incremental packetizer and mono PCM producer, with at most 20 ms chunks."""

    def __init__(self, settings=None, profile="checked"):
        self.settings = settings or AFSKSettings()
        if profile not in PROFILES:
            raise ValueError("unknown audiolink profile")
        self.profile = profile
        self.samples = 0
        self._session = secrets.token_bytes(8)
        self._sequence = 0
        self._pending = bytearray()
        self._finished = False
        self._previous = False
        self._space = False

    def _characters(self, text):
        if not isinstance(text, str):
            raise ValueError("audiolink input must be ASCII text")
        for character in text:
            if self.profile == "text":
                character = normalize_character(character, "text")
                if character == " ":
                    if self._previous:
                        self._space = True
                    continue
                if self._space:
                    yield 32
                    self._space = False
                self._previous = True
            elif ord(character) > 127:
                raise ValueError("audiolink input must be ASCII")
            yield ord(character)

    def feed(self, text):
        if self._finished:
            raise ValueError("encoder is already finished")
        for value in self._characters(text):
            self._pending.append(value)
            if len(self._pending) == self.settings.packet_size:
                yield from self.flush()

    def _packet(self, payload, end=False):
        if self._sequence > 0xffffffff or (not end and self._sequence == 0xffffffff):
            raise ValueError("audiolink sequence space exhausted")
        header = _header(self._session, self._sequence, len(payload), end)
        bits = np.concatenate((TRAINING, SYNC, _fec_encode(header), _fec_encode(payload + _crc(header + payload))))
        settings = self.settings
        lead = round(settings.sample_rate * settings.lead_ms / 1000)
        count = round(len(bits) * settings.sample_rate / BAUD)
        tail = round(settings.sample_rate * settings.tail_ms / 1000)
        chunk_size = max(1, round(settings.sample_rate * .020))
        phase = 0.0
        # Lead is a mark tone to permit VOX/key-up and squelch acquisition.
        # Only burst edges ramp; frequency transitions remain phase-continuous.
        total_tone = lead + count
        ramp = min(round(.004 * settings.sample_rate), total_tone // 4)
        for start in range(0, total_tone, chunk_size):
            indexes = np.arange(start, min(start + chunk_size, total_tone))
            bit_indexes = np.maximum(0, np.floor((indexes - lead) * BAUD / settings.sample_rate).astype(int))
            frequencies = np.where((indexes < lead) | (bits[np.minimum(bit_indexes, len(bits) - 1)] == 1), MARK, SPACE)
            phases = phase + np.cumsum(2 * np.pi * frequencies / settings.sample_rate)
            phase = float(phases[-1] % (2 * np.pi))
            pcm = .65 * np.sin(phases)
            if ramp:
                pcm *= np.maximum(0, np.minimum(1, np.minimum(indexes / ramp, (total_tone - 1 - indexes) / ramp)))
            self.samples += len(pcm)
            yield pcm.astype(np.float32)
        for start in range(0, tail, chunk_size):
            pcm = np.zeros(min(chunk_size, tail - start), dtype=np.float32)
            self.samples += len(pcm)
            yield pcm
        self._sequence += 1

    def flush(self):
        if self._pending:
            payload = bytes(self._pending)
            self._pending.clear()
            yield from self._packet(payload)

    def finish(self):
        if not self._finished:
            yield from self.flush()
            yield from self._packet(b"", end=True)
            self._finished = True


def _normalized(text, profile):
    encoder = AFSKEncoder(profile=profile)
    return bytes(encoder._characters(text))


def estimate_duration(text, settings=None, profile="checked", *, finish=True):
    """Exact batch feed/flush duration, with an optional explicit end packet."""
    settings = settings or AFSKSettings()
    size = len(_normalized(text, profile))
    lengths = [min(settings.packet_size, size - i) for i in range(0, size, settings.packet_size)] + ([0] if finish else [])
    samples = sum(round(settings.sample_rate * (len(TRAINING) + len(SYNC) + HEADER_BITS + (length + 4) * 16) / BAUD)
                  + round(settings.sample_rate * settings.lead_ms / 1000)
                  + round(settings.sample_rate * settings.tail_ms / 1000) for length in lengths)
    return samples / settings.sample_rate


class AFSKDecoder:
    """Noncoherent matched-tone receiver with independent packet acquisition.

    Four samples per symbol are retained after streaming tone correlation. Header
    CRC bounds packet lengths before allocation. A short clock/phase search uses
    FEC and packet CRC, never an expected payload. Retention is under five seconds
    at the largest supported packet size; pipe/audio queues remain independent.
    """

    def __init__(self, sample_rate=48000, profile="checked"):
        AFSKSettings(sample_rate)
        if profile not in PROFILES:
            raise ValueError("unknown audiolink profile")
        self.sample_rate = sample_rate
        self.profile = profile
        self.diagnostics = []
        self.error_count = 0
        self.complete = False
        self._finished = False
        self._session = None
        self._expected = 0
        self._seen_sessions = deque(maxlen=64)
        self._sos = signal.butter(3, [300, 3000], btype="bandpass", fs=sample_rate, output="sos")
        self._filter_state = np.zeros((len(self._sos), 2))
        self._window = round(sample_rate / BAUD)
        self._kernel = np.ones(self._window) / self._window
        self._tone_states = [np.zeros(self._window - 1, dtype=np.complex128) for _ in range(2)]
        self._input_count = 0
        self._next_metric = 0.0
        self._last_metric = 0.0
        self._metrics = np.empty(0, dtype=np.float32)
        self._candidate = None
        self._header_value = None
        self._noticed = False
        self._text_previous = False
        self._text_space = False

    def _error(self, message):
        self.error_count += 1
        if len(self.diagnostics) < 100:
            self.diagnostics.append(message)
        if self.profile == "raw":
            raise AudioError(message)
        return "?"

    def discontinuity(self, message="audio sample discontinuity"):
        self._metrics = np.empty(0, dtype=np.float32)
        self._candidate = None
        self._header_value = None
        return self._error(message)

    def _demodulate(self, pcm):
        filtered, self._filter_state = signal.sosfilt(self._sos, pcm, zi=self._filter_state)
        positions = np.arange(self._input_count, self._input_count + len(pcm))
        energies = []
        for index, frequency in enumerate((MARK, SPACE)):
            mixed = filtered * np.exp((-2j * np.pi * frequency / self.sample_rate) * positions)
            correlated, self._tone_states[index] = signal.lfilter(self._kernel, [1], mixed, zi=self._tone_states[index])
            energies.append(np.abs(correlated) ** 2)
        power = energies[0] + energies[1]
        metric = np.divide(energies[0] - energies[1], power + 1e-12)
        metric[power < 1e-8] = 0
        step = self.sample_rate / (4 * BAUD)
        end = self._input_count + len(pcm) - 1
        count = max(0, math.floor((end - self._next_metric) / step + 1e-8) + 1)
        times = self._next_metric + np.arange(count) * step
        values = np.interp(times, np.arange(self._input_count - 1, end + 1), np.concatenate(([self._last_metric], metric)))
        self._next_metric += count * step
        self._input_count += len(pcm)
        self._last_metric = float(metric[-1])
        self._metrics = np.concatenate((self._metrics, values.astype(np.float32)))

    def _find_sync(self):
        signs = SYNC.astype(float) * 2 - 1
        candidates = []
        for phase in range(4):
            values = self._metrics[phase::4]
            if len(values) < len(SYNC):
                continue
            scores = np.correlate(values, signs, mode="valid") / len(SYNC)
            for index in np.flatnonzero(scores >= .55):
                observed = values[index:index + len(SYNC)]
                if np.count_nonzero((observed > 0) != SYNC) <= 3:
                    candidates.append((float(scores[index]), phase + int(index) * 4))
        if not candidates:
            # Retain enough for a sync straddling the next input chunk.
            self._metrics = self._metrics[-(len(SYNC) + 4) * 4:]
            return False
        # Prefer the first packet, then the strongest phase for that packet.
        # This also preserves order while recovering after a truncated packet.
        earliest = min(position for _, position in candidates)
        _, start = max((score, position) for score, position in candidates if position <= earliest + 4)
        self._metrics = self._metrics[max(0, start - 4):]
        self._candidate = min(start, 4)
        self._header_value = None
        self._noticed = True
        return True

    def _bits(self, start, count, clock, offset=0):
        times = start + offset + np.arange(count) * (4 * clock)
        return (np.interp(times, np.arange(len(self._metrics)), self._metrics) > 0).astype(np.uint8)

    def _read_header(self):
        start = self._candidate + len(SYNC) * 4
        for clock in _CLOCKS:
            for offset in (0, -.5, .5, -1, 1):
                try:
                    raw = _fec_decode(self._bits(start, HEADER_BITS, clock, offset))
                    if raw[-4:] != _crc(raw[:-4]):
                        continue
                    magic, version, flag, session, sequence, length = HEADER.unpack(raw[:-4])
                    if magic != b"AL" or version != 1 or flag not in (0, 1) or length > MAX_PAYLOAD:
                        continue
                    if (flag == 1 and length != 0) or (flag == 0 and length == 0):
                        continue
                    return raw, session, sequence, length, bool(flag)
                except ValueError:
                    continue
        return None

    def _read_payload(self, header):
        raw, _, _, length, _ = header
        count = (length + 4) * 16
        # Account for clock error accumulated since the beginning of the header.
        for clock in _CLOCKS:
            clock_start = self._candidate + (len(SYNC) + HEADER_BITS) * (4 * clock)
            for offset in (0, -.5, .5, -1, 1):
                try:
                    body = _fec_decode(self._bits(clock_start, count, clock, offset))
                except ValueError:
                    continue
                if body[-4:] == _crc(raw + body[:-4]):
                    try:
                        return body[:-4].decode("ascii")
                    except UnicodeDecodeError:
                        return None
        return None

    def _accept(self, header, payload):
        _, session, sequence, _, end = header
        output = ""
        if session != self._session:
            if session in self._seen_sessions:
                return ""
            if self._session is not None and not self.complete:
                output += self._error("previous audiolink session ended without an end packet")
            self._seen_sessions.append(session)
            self._session = session
            self._expected = 0
            self.complete = False
        if sequence < self._expected:
            return output
        if self.complete:
            return output + self._error("audiolink data received after end packet")
        if sequence > self._expected:
            output += self._error(f"audiolink packet gap: expected {self._expected}, received {sequence}")
        self._expected = sequence + 1
        if end:
            self.complete = True
        else:
            if self.profile == "text":
                try:
                    characters = [normalize_character(c, "text") for c in payload]
                except ValueError:
                    return output + self._error("unsupported character in audiolink text packet")
                for character in characters:
                    if character == " ":
                        if self._text_previous:
                            self._text_space = True
                    else:
                        if self._text_space:
                            output += " "
                            self._text_space = False
                        output += character
                        self._text_previous = True
            else:
                output += payload
        return output

    def _process(self, final=False):
        output = ""
        while True:
            if self._candidate is None and not self._find_sync():
                break
            header_end = self._candidate + (len(SYNC) + HEADER_BITS) * 4
            if len(self._metrics) < header_end + 8:
                break
            if self._header_value is None:
                self._header_value = self._read_header()
                if self._header_value is None:
                    output += self._error("audiolink packet header failed FEC or CRC")
                    self._metrics = self._metrics[self._candidate + len(SYNC) * 4:]
                    self._candidate = None
                    continue
            length = self._header_value[3]
            packet_end = header_end + (length + 4) * 16 * 4
            if len(self._metrics) < packet_end + 12 and not final:
                break
            if len(self._metrics) < packet_end - 4:
                if final:
                    output += self._error("truncated audiolink packet")
                    self._metrics = self._metrics[self._candidate + len(SYNC) * 4:]
                    self._candidate = None
                    self._header_value = None
                    continue
                break
            payload = self._read_payload(self._header_value)
            if payload is None:
                output += self._error("audiolink packet payload failed FEC, CRC or ASCII validation")
                # Search the buffered region: a truncated packet may be followed
                # immediately by an intact packet with a different length.
                self._metrics = self._metrics[self._candidate + len(SYNC) * 4:]
            else:
                output += self._accept(self._header_value, payload)
                self._metrics = self._metrics[max(0, packet_end - 4):]
            self._candidate = None
            self._header_value = None
        return output

    def feed(self, pcm):
        if self._finished:
            raise ValueError("decoder is already finished")
        pcm = np.asarray(pcm, dtype=np.float32)
        if pcm.ndim != 1 or not np.all(np.isfinite(pcm)):
            raise ValueError("audiolink PCM must be finite mono samples")
        output = ""
        # Bound internal work even if a caller supplies an entire recording.
        chunk = max(1, round(self.sample_rate * .040))
        for start in range(0, len(pcm), chunk):
            self._demodulate(pcm[start:start + chunk])
            output += self._process()
        return output

    def finish(self):
        if self._finished:
            return ""
        # Flush the causal filter/correlator delay, including a zero-tail burst.
        # This supplies only silence, not replacement tone observations.
        self._demodulate(np.zeros(max(1, round(self.sample_rate * .010)), dtype=np.float32))
        output = self._process(final=True)
        self._finished = True
        if self._candidate is not None:
            output += self._error("truncated audiolink packet")
        if self._noticed and not self.complete:
            output += self._error("missing audiolink end packet")
        return output


def write_wav(path, text, settings=None, profile="checked"):
    settings = settings or AFSKSettings()
    encoder = AFSKEncoder(settings, profile)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(settings.sample_rate)
        for chunks in (encoder.feed(text), encoder.finish()):
            for pcm in chunks:
                target.writeframesraw((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    return {"samples": encoder.samples, "duration": encoder.samples / settings.sample_rate,
            "sample_rate": settings.sample_rate}


def decode_wav(path, profile="checked"):
    with wave.open(str(path), "rb") as source:
        rate = source.getframerate()
    decoder = AFSKDecoder(rate, profile)
    output = []
    for chunk in iter_wav(path):
        output.append(decoder.feed(chunk))
    output.append(decoder.finish())
    return "".join(output), decoder.diagnostics
