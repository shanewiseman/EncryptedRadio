"""Bounded streaming Morse synthesis and actual PCM signal decoding.

No transmitter state or expected message is supplied to the receiver. Timing is
estimated from detected pulse lengths, and spectral acquisition chooses a single
foreground tone. Live devices and WAV files use these same classes.
"""

from collections import deque
from dataclasses import dataclass
import math
from pathlib import Path
import wave

import numpy as np
from scipy import signal

from .morse import MORSE, PROFILES, REVERSE_MORSE, normalize_character


class AudioError(ValueError):
    """Unrecoverable audio discontinuity or invalid signal."""


@dataclass(frozen=True)
class AudioSettings:
    sample_rate: int = 48000
    frequency: float = 700.0
    wpm: float = 20.0

    def __post_init__(self):
        if not isinstance(self.sample_rate, int) or not 8000 <= self.sample_rate <= 192000:
            raise ValueError("sample rate must be an integer from 8000 to 192000 Hz")
        if not math.isfinite(self.frequency) or not 400 <= self.frequency <= 1200:
            raise ValueError("frequency must be between 400 and 1200 Hz")
        if not math.isfinite(self.wpm) or not 8 <= self.wpm <= 30:
            raise ValueError("speed must be between 8 and 30 WPM")


class MorseEncoder:
    """Incremental synthesis, with chunks of at most 20 ms.

    The three-unit gap is emitted after each character, so an idle stdin does
    not delay its decoding. Text word boundaries add four more units.
    """

    def __init__(self, settings: AudioSettings | None = None, profile="checked"):
        self.settings = settings or AudioSettings()
        if profile not in PROFILES:
            raise ValueError("unknown Morse profile")
        self.profile = profile
        self._previous = False
        self._word_gap = False
        self._finished = False
        self.samples = 0

    def _segment(self, units, tone):
        settings = self.settings
        length = round(units * 1.2 / settings.wpm * settings.sample_rate)
        ramp = min(round(0.004 * settings.sample_rate), length // 4)
        chunk = max(1, round(settings.sample_rate * 0.020))
        for start in range(0, length, chunk):
            count = min(chunk, length - start)
            if tone:
                positions = np.arange(start, start + count)
                pcm = 0.65 * np.sin(positions * (2 * np.pi * settings.frequency / settings.sample_rate))
                envelope = np.minimum(1.0, np.minimum(positions / ramp, (length - 1 - positions) / ramp))
                pcm *= np.maximum(0, envelope)
                pcm = pcm.astype(np.float32)
            else:
                pcm = np.zeros(count, dtype=np.float32)
            self.samples += count
            yield pcm

    def feed(self, text):
        if self._finished:
            raise ValueError("encoder is already finished")
        for character in text:
            character = normalize_character(character, self.profile)
            if character == " ":
                if self._previous and not self._word_gap:
                    yield from self._segment(4, False)
                    self._word_gap = True
                continue
            for index, element in enumerate(MORSE[character]):
                if index:
                    yield from self._segment(1, False)
                yield from self._segment(1 if element == "." else 3, True)
            yield from self._segment(3, False)
            self._previous = True
            self._word_gap = False

    def finish(self):
        if not self._finished:
            self._finished = True
            # An additional final gap allows filter settling at slow speeds.
            yield from self._segment(1, False)


def estimate_duration(text, settings=None, profile="checked", *, finish=True):
    settings = settings or AudioSettings()
    if profile not in PROFILES:
        raise ValueError("unknown Morse profile")
    samples = round(1.2 / settings.wpm * settings.sample_rate) if finish else 0
    previous = False
    gap = False
    for character in text:
        character = normalize_character(character, profile)
        if character == " ":
            if previous and not gap:
                samples += round(4 * 1.2 / settings.wpm * settings.sample_rate)
                gap = True
            continue
        pattern = MORSE[character]
        samples += sum(round((1 if c == "." else 3) * 1.2 / settings.wpm * settings.sample_rate) for c in pattern)
        samples += (len(pattern) - 1) * round(1.2 / settings.wpm * settings.sample_rate)
        samples += round(3 * 1.2 / settings.wpm * settings.sample_rate)
        previous, gap = True, False
    return samples / settings.sample_rate


class MorseDecoder:
    """Incremental narrowband envelope receiver with automatic tone and timing.

    Acquisition requires a spectrally concentrated signal, then locks its pitch.
    Timing acquisition requires both short and long pulses. Checked streams carry
    VVV training for this reason. A manual WPM bypasses timing ambiguity.
    """

    def __init__(self, sample_rate=48000, profile="checked", frequency=None, wpm=None):
        AudioSettings(sample_rate, frequency or 700, wpm or 20)
        if frequency is not None and (not math.isfinite(frequency) or not 400 <= frequency <= 1200):
            raise ValueError("receiver frequency must be between 400 and 1200 Hz")
        if wpm is not None and (not math.isfinite(wpm) or not 8 <= wpm <= 30):
            raise ValueError("receiver speed must be between 8 and 30 WPM")
        if profile not in PROFILES:
            raise ValueError("unknown Morse profile")
        self.sample_rate = sample_rate
        self.profile = profile
        self.frequency = frequency
        self._manual_frequency = frequency
        self.wpm = wpm
        self.diagnostics = []
        self.error_count = 0
        self._unit = 1.2 / wpm if wpm else None
        self._manual_timing = wpm is not None
        self._frame = round(sample_rate * 0.005)
        self._pending_pcm = np.empty(0, dtype=np.float32)
        self._acquisition = np.empty(0, dtype=np.float32)
        self._acquire_count = round(sample_rate * 0.050)
        self._sos = None
        self._zi = None
        self._peak = 0.1
        self._noise = 0.001
        self._tone = False
        self._run = 0.0
        self._runs = []
        self._lengths = deque(maxlen=64)
        self._candidate_seconds = 0.0
        self._candidate_started = False
        self._pattern = ""
        self._char_flushed = False
        self._word_flushed = False
        self._output = []
        self._had_character = False
        self._pending_space = False
        self._finished = False

    def _set_frequency(self, frequency):
        self.frequency = float(frequency)
        self._sos = signal.butter(3, [frequency - 90, frequency + 90], btype="bandpass", fs=self.sample_rate, output="sos")
        self._zi = np.zeros((len(self._sos), 2))

    def _acquire(self, pcm):
        window = np.hanning(len(pcm))
        size = 1 << (len(pcm) * 4 - 1).bit_length()
        spectrum = np.abs(np.fft.rfft(pcm * window, n=size)) ** 2
        frequencies = np.fft.rfftfreq(size, 1 / self.sample_rate)
        band = (frequencies >= 400) & (frequencies <= 1200)
        indices = np.flatnonzero(band)
        peak = indices[np.argmax(spectrum[band])]
        frequency = frequencies[peak]
        if self._manual_frequency is not None and abs(frequency - self._manual_frequency) > 45:
            return False
        background = np.median(spectrum[band]) + 1e-20
        concentrated = spectrum[np.abs(frequencies - frequency) < 35].sum()
        if np.sqrt(np.mean(pcm * pcm)) < 1e-4 or spectrum[peak] / background < 35 or concentrated / (spectrum.sum() + 1e-20) < 0.50:
            return False
        self._peak = max(1e-4, float(np.sqrt(np.mean(pcm * pcm))))
        self._set_frequency(self._manual_frequency if self._manual_frequency is not None else frequency)
        return True

    def _error(self, message):
        self.error_count += 1
        if len(self.diagnostics) < 127:
            self.diagnostics.append(message)
        elif len(self.diagnostics) == 127:
            self.diagnostics.append("further reception diagnostics suppressed (see error_count)")
        if self.profile == "raw":
            raise AudioError(message)
        self._output.append("?")
        self._pattern = ""

    def discontinuity(self, reason="audio sample discontinuity"):
        self._error(reason)
        self._pattern = ""
        self._runs.clear()
        self._run = 0.0
        self._tone = False
        return self._take_output()

    def _take_output(self):
        result = "".join(self._output)
        self._output.clear()
        return result

    def _estimate_timing(self):
        if len(self._lengths) < 4:
            return
        lengths = np.asarray(self._lengths)
        short = float(np.quantile(lengths, 0.2))
        long = float(np.max(lengths))
        if not 2.0 <= long / max(short, 1e-6) <= 4.7:
            return
        split = (short + long) / 2
        short_group = lengths[lengths < split]
        long_group = lengths[lengths >= split]
        if not len(short_group) or not len(long_group):
            return
        guess = float((np.median(short_group) + np.median(long_group) / 3) / 2)
        if not 0.034 <= guess <= 0.175:
            return
        self._unit = min(0.15, max(0.04, guess))
        self.wpm = 1.2 / self._unit
        runs, self._runs = self._runs, []
        for tone, length in runs:
            self._consume_run(tone, length)

    def _consume_run(self, tone, length):
        if tone:
            ratio = length / self._unit
            if ratio < 0.55 or ratio > 4.0 or 1.5 < ratio < 2.1:
                self._error(f"unreliable Morse pulse ({length:.3f} seconds)")
            else:
                self._pattern += "." if ratio < 1.5 else "-"
                if len(self._pattern) > 6:
                    self._error("Morse character exceeds six elements")
            self._char_flushed = False
            self._word_flushed = False
        else:
            self._consume_silence(length)

    def _consume_silence(self, length):
        if length >= 1.9 * self._unit and not self._char_flushed:
            if self._pattern:
                character = REVERSE_MORSE.get(self._pattern)
                if character is None:
                    self._error(f"unrecognized Morse character {self._pattern!r}")
                else:
                    if self._pending_space:
                        self._output.append(" ")
                        self._pending_space = False
                    self._output.append(character)
                    self._had_character = True
                self._pattern = ""
            self._char_flushed = True
        if self.profile == "text" and length >= 5 * self._unit and not self._word_flushed and self._had_character:
            # A long idle period is a pending word boundary, not trailing data.
            self._pending_space = True
            self._word_flushed = True

    def _end_run(self):
        if self._tone and self._run >= 0.015:
            self._lengths.append(self._run)
        if self._unit is None:
            self._runs.append((self._tone, self._run))
            if self._tone:
                self._estimate_timing()
        else:
            self._consume_run(self._tone, self._run)
            if self._tone and not self._manual_timing and len(self._lengths) >= 4:
                # Follow gradual hand-keying speed changes without changing the
                # pitch lock or reinterpreting characters already emitted.
                ratio = 1 if self._run / self._unit < 1.85 else 3
                observation = self._run / ratio
                if 0.65 * self._unit < observation < 1.4 * self._unit:
                    self._unit = min(0.15, max(0.04, self._unit * 0.98 + observation * 0.02))
                    self.wpm = 1.2 / self._unit

    def _process(self, pcm):
        filtered, self._zi = signal.sosfilt(self._sos, pcm, zi=self._zi)
        energy = np.sqrt(np.mean(filtered * filtered))
        self._peak = max(float(energy), self._peak * 0.9995)
        # Noise updates only below the low threshold. This avoids tracking the
        # useful carrier into the noise estimate during sustained dashes.
        if energy < self._peak * 0.20:
            self._noise = 0.98 * self._noise + 0.02 * energy
        threshold = max(self._peak * (0.20 if self._tone else 0.32), self._noise * (2.2 if self._tone else 3.5), 1e-5)
        tone = bool(energy > threshold)
        if tone != self._tone:
            self._end_run()
            self._tone, self._run = tone, 0.0
        step = len(pcm) / self.sample_rate
        self._run += step
        if self._unit is None:
            if tone:
                self._candidate_started = True
            if self._candidate_started and (tone or self._run < 0.6):
                self._candidate_seconds += step
            if self._candidate_seconds > 10:
                self._error("could not distinguish Morse speed within ten seconds; specify --wpm")
                self._runs.clear()
                self._lengths.clear()
                self._candidate_seconds = 0
                self._candidate_started = False
        elif not tone:
            self._consume_silence(self._run)

    def feed(self, pcm):
        if self._finished:
            raise ValueError("decoder is already finished")
        pcm = np.asarray(pcm, dtype=np.float32)
        if pcm.ndim != 1 or not np.isfinite(pcm).all():
            raise ValueError("PCM must be finite, mono samples")
        # Iterate bounded pieces even when a caller submits a whole recording.
        for offset in range(0, len(pcm), self.sample_rate):
            part = pcm[offset:offset + self.sample_rate]
            if self._sos is None:
                self._acquisition = np.concatenate((self._acquisition, part))
                while len(self._acquisition) >= self._acquire_count and self._sos is None:
                    candidate = self._acquisition[:self._acquire_count]
                    if self._acquire(candidate):
                        part, self._acquisition = self._acquisition, np.empty(0, dtype=np.float32)
                    else:
                        self._acquisition = self._acquisition[self._acquire_count:]
                if self._sos is None:
                    continue
            self._pending_pcm = np.concatenate((self._pending_pcm, part))
            used = len(self._pending_pcm) // self._frame * self._frame
            for start in range(0, used, self._frame):
                self._process(self._pending_pcm[start:start + self._frame])
            self._pending_pcm = self._pending_pcm[used:].copy()
        return self._take_output()

    def finish(self):
        if self._finished:
            return ""
        self._finished = True
        if self._sos is not None:
            if len(self._pending_pcm):
                self._process(self._pending_pcm)
            if self._tone:
                self._error("audio ended during a Morse pulse")
            if self._unit is None and self._lengths:
                self._error("ambiguous Morse timing at end of input; specify --wpm")
            elif self._unit is not None:
                self._consume_silence(3 * self._unit)
        return self._take_output()


def write_wav(path: str | Path, text, settings=None, profile="checked"):
    settings = settings or AudioSettings()
    encoder = MorseEncoder(settings, profile)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(settings.sample_rate)
        for chunk in encoder.feed(text):
            output.writeframesraw((np.clip(chunk, -1, 1) * 32767).astype("<i2").tobytes())
        for chunk in encoder.finish():
            output.writeframesraw((np.clip(chunk, -1, 1) * 32767).astype("<i2").tobytes())
    return {"samples": encoder.samples, "duration": encoder.samples / settings.sample_rate, "sample_rate": settings.sample_rate}


def iter_wav(path, chunk_frames=4096):
    """Read mono integer PCM WAV without retaining the recording in memory."""
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() not in (1, 2, 3, 4) or source.getcomptype() != "NONE":
            raise ValueError("WAV must contain mono, uncompressed integer PCM")
        width = source.getsampwidth()
        while data := source.readframes(chunk_frames):
            if width == 1:
                pcm = (np.frombuffer(data, dtype=np.uint8).astype(np.float32) - 128) / 128
            elif width == 3:
                b = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
                values = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
                values = (values ^ 0x800000) - 0x800000
                pcm = values.astype(np.float32) / 8388608
            else:
                pcm = np.frombuffer(data, dtype=f"<i{width}").astype(np.float32) / (2 ** (8 * width - 1))
            yield pcm


def decode_wav(path, profile="checked", frequency=None, wpm=None):
    with wave.open(str(path), "rb") as source:
        decoder = MorseDecoder(source.getframerate(), profile, frequency, wpm)
    output = [decoder.feed(pcm) for pcm in iter_wav(path)]
    output.append(decoder.finish())
    return "".join(output), decoder.diagnostics
