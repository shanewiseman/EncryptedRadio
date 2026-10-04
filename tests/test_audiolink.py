"""Reproducible packet-modem PCM fixtures; these are not hardware tests."""

from contextlib import redirect_stderr, redirect_stdout
import io
import itertools
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

import numpy as np
from scipy import signal

from encrypted_radio import audiolink_cli, packet_audio
from encrypted_radio.audio import AudioError
from encrypted_radio.packet_audio import (
    AFSKDecoder, AFSKEncoder, AFSKSettings, HEADER_BITS, SYNC, TRAINING,
    _fec_decode, _fec_encode, decode_wav, estimate_duration, write_wav,
)


def synthesize(text, settings=None, profile="checked", session=None):
    encoder = AFSKEncoder(settings, profile)
    if session is not None:
        encoder._session = session  # Public, deterministic transport fixture only.
    return np.concatenate([*encoder.feed(text), *encoder.finish()])


def decode(pcm, sample_rate=48000, profile="checked", chunks=(137, 960, 4093, 1024)):
    decoder = AFSKDecoder(sample_rate, profile)
    output = []
    position = 0
    for size in itertools.cycle(chunks):
        if position >= len(pcm):
            break
        output.append(decoder.feed(pcm[position:position + size]))
        position += size
    output.append(decoder.finish())
    return "".join(output), decoder


def band_filter(pcm, rate):
    return signal.sosfilt(signal.butter(4, [300, 3000], fs=rate, btype="bandpass", output="sos"), pcm)


def noise_at_snr(pcm, rate, snr=10, seed=20261003):
    noise = band_filter(np.random.default_rng(seed).standard_normal(len(pcm)), rate)
    # Both powers include the complete waveform and its silence/guards.
    noise *= math.sqrt(float(np.mean(pcm ** 2) / np.mean(noise ** 2)) / 10 ** (snr / 10))
    return pcm + noise


class CodingTests(unittest.TestCase):
    def test_independent_hamming_vector_and_single_error_correction(self):
        # Codewords for hexadecimal 0 and 1 are 00000000 and 11010010;
        # wire bit-plane interleaving alternates the corresponding bits.
        expected = np.array([0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0], dtype=np.uint8)
        np.testing.assert_array_equal(_fec_encode(b"\x01"), expected)
        self.assertEqual(_fec_decode(expected), b"\x01")
        for index in range(len(expected)):
            damaged = expected.copy()
            damaged[index] ^= 1
            self.assertEqual(_fec_decode(damaged), b"\x01")
        damaged = expected.copy()
        damaged[[0, 2]] ^= 1  # Two bits in the same codeword.
        with self.assertRaisesRegex(ValueError, "uncorrectable"):
            _fec_decode(damaged)

    def test_interleaving_corrects_burst(self):
        source = bytes(range(128))
        encoded = _fec_encode(source)
        encoded[19:119] ^= 1  # One bad bit in each affected codeword.
        self.assertEqual(_fec_decode(encoded), source)
        with self.assertRaises(ValueError):
            _fec_decode(np.zeros(7, dtype=np.uint8))

    def test_settings_and_input_validation(self):
        for kwargs in ({"sample_rate": 7999}, {"baud": 2400}, {"mark": 700}, {"space": 3000},
                       {"packet_size": 0}, {"packet_size": 257}, {"lead_ms": -1},
                       {"tail_ms": 2001}, {"lead_ms": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AFSKSettings(**kwargs)
        with self.assertRaises(ValueError):
            list(AFSKEncoder().feed("non-ASCII é"))
        with self.assertRaises(ValueError):
            list(AFSKEncoder(profile="text").feed("unsupported_"))
        for pcm in (np.array([[0.0]]), np.array([float("nan")])):
            with self.assertRaises(ValueError):
                AFSKDecoder().feed(pcm)
        with self.assertRaises(ValueError):
            AFSKDecoder(profile="bad")

    def test_final_sequence_reserved_for_end(self):
        encoder = AFSKEncoder()
        encoder._sequence = 0xffffffff
        list(encoder.feed("data"))
        with self.assertRaisesRegex(ValueError, "sequence space"):
            list(encoder.flush())
        encoder = AFSKEncoder()
        encoder._sequence = 0xffffffff
        self.assertTrue(list(encoder.finish()))
        self.assertEqual(encoder._sequence, 0x100000000)


class PacketAudioTests(unittest.TestCase):
    def test_all_ascii_and_arbitrary_text_pcm_chunks(self):
        text = bytes(range(128)).decode("ascii") * 3
        for rate in (44100, 48000):
            with self.subTest(rate=rate):
                settings = AFSKSettings(sample_rate=rate)
                encoder = AFSKEncoder(settings)
                chunks = []
                for start in range(0, len(text), 7):
                    chunks.extend(encoder.feed(text[start:start + 7]))
                chunks.extend(encoder.finish())
                self.assertTrue(all(len(c) <= round(rate * .020) for c in chunks))
                pcm = np.concatenate(chunks)
                received, decoder = decode(pcm, rate)
                self.assertEqual(received, text)
                self.assertEqual(decoder.diagnostics, [])
                self.assertTrue(decoder.complete)
                self.assertAlmostEqual(len(pcm) / rate, estimate_duration(text, settings))

    def test_text_profile_matches_morse_normalization_across_chunks(self):
        encoder = AFSKEncoder(AFSKSettings(packet_size=3), "text")
        chunks = []
        for text in ("  hel", "lo\n", "\tworld!".replace("!", "."), "   "):
            chunks.extend(encoder.feed(text))
        chunks.extend(encoder.finish())
        result, decoder = decode(np.concatenate(chunks), profile="text")
        self.assertEqual(result, "HELLO WORLD.")
        self.assertFalse(decoder.diagnostics)
        # Receiver normalization is not trusted to the transmitter.
        result, decoder = decode(synthesize(" \tMixed\n case  "), profile="text")
        self.assertEqual(result, "MIXED CASE")
        self.assertFalse(decoder.diagnostics)
        result, decoder = decode(synthesize("secret_unsupported"), profile="text")
        self.assertEqual(result, "?")
        self.assertTrue(decoder.diagnostics)

    def test_packet_size_guards_and_exact_duration_boundaries(self):
        for rate, packet_size, lead, tail in itertools.product((44100, 48000), (1, 256), (0, 200), (0, 50)):
            settings = AFSKSettings(sample_rate=rate, packet_size=packet_size, lead_ms=lead, tail_ms=tail)
            with self.subTest(rate=rate, packet_size=packet_size, lead=lead, tail=tail):
                encoder = AFSKEncoder(settings)
                data_pcm = [*encoder.feed("AB"), *encoder.flush()]
                self.assertAlmostEqual(sum(map(len, data_pcm)) / rate,
                                       estimate_duration("AB", settings, finish=False))
                pcm = np.concatenate([*data_pcm, *encoder.finish()])
                result, decoder = decode(pcm, rate)
                self.assertEqual(result, "AB")
                self.assertEqual(decoder.diagnostics, [])
                self.assertAlmostEqual(len(pcm) / rate, estimate_duration("AB", settings))
                self.assertEqual(list(encoder.finish()), [])
                self.assertEqual(decoder.finish(), "")
                with self.assertRaises(ValueError):
                    list(encoder.feed("C"))
                with self.assertRaises(ValueError):
                    decoder.feed(np.zeros(1))

    def test_empty_transfer_is_explicit_end(self):
        pcm = synthesize("")
        result, decoder = decode(pcm)
        self.assertEqual(result, "")
        self.assertTrue(decoder.complete)
        self.assertFalse(decoder.diagnostics)

    def test_long_pauses_and_idle_flush_preserve_state(self):
        encoder = AFSKEncoder()
        decoder = AFSKDecoder()
        output = []
        for text in ("FIRST", "SECOND"):
            chunks = [*encoder.feed(text), *encoder.flush()]
            output.extend(decoder.feed(c) for c in chunks)
            self.assertEqual(decoder.feed(np.zeros(48000 * 3)), "")
        output.extend(decoder.feed(c) for c in encoder.finish())
        output.append(decoder.finish())
        self.assertEqual("".join(output), "FIRSTSECOND")
        self.assertTrue(decoder.complete)
        self.assertFalse(decoder.diagnostics)

    def test_silence_and_noise_are_inert_and_buffer_is_bounded(self):
        decoder = AFSKDecoder()
        noise = np.random.default_rng(99).normal(0, .1, 48000 * 3)
        self.assertEqual(decoder.feed(np.zeros(48000 * 10)), "")
        self.assertEqual(decoder.feed(noise), "")
        self.assertLess(len(decoder._metrics), 300)
        self.assertEqual(decoder.finish(), "")
        self.assertFalse(decoder.diagnostics)
        self.assertFalse(decoder.complete)

    def test_missing_duplicate_reordered_packets_and_raw_failure(self):
        encoder = AFSKEncoder()
        packets = []
        for text in ("ONE", "TWO", "THREE"):
            packets.append(np.concatenate([*encoder.feed(text), *encoder.flush()]))
        packets.append(np.concatenate(list(encoder.finish())))
        result, decoder = decode(np.concatenate([packets[0], packets[2], packets[3]]))
        self.assertEqual(result, "ONE?THREE")
        self.assertTrue(decoder.complete)
        self.assertIn("gap", decoder.diagnostics[0])
        result, decoder = decode(np.concatenate([packets[0], packets[1], packets[1], packets[2], packets[3]]))
        self.assertEqual(result, "ONETWOTHREE")
        self.assertFalse(decoder.diagnostics)
        result, decoder = decode(np.concatenate([packets[0], packets[2], packets[1], packets[3]]))
        self.assertEqual(result, "ONE?THREE")
        self.assertTrue(decoder.diagnostics)
        with self.assertRaises(AudioError):
            decode(np.concatenate([packets[0], packets[2], packets[3]]), profile="raw")

    def test_corrupt_body_and_header_recovery_uses_audio(self):
        original_fec = _fec_encode
        for target, error_bits in itertools.product((0, 1), (2, 3)):
            calls = 0

            def corrupt(data):
                nonlocal calls
                bits = original_fec(data).copy()
                if calls == target:
                    # Two errors are detected by FEC; three can miscorrect
                    # to a different valid codeword and must fail CRC.
                    bits[np.arange(error_bits) * (len(bits) // 8)] ^= 1
                calls += 1
                return bits

            encoder = AFSKEncoder()
            with patch("encrypted_radio.packet_audio._fec_encode", side_effect=corrupt):
                broken = [*encoder.feed("BROKEN"), *encoder.flush()]
            good = [*encoder.feed("LATER"), *encoder.finish()]
            result, decoder = decode(np.concatenate([*broken, *good]))
            self.assertNotIn("BROKEN", result)
            self.assertTrue(result.endswith("LATER"))
            self.assertTrue(decoder.complete)
            self.assertTrue(decoder.diagnostics)

    def test_oversized_crc_valid_header_is_rejected_before_body(self):
        encoder = AFSKEncoder()
        header = packet_audio._header

        def oversized(session, sequence, length, end=False):
            return header(session, sequence, 257, end)

        with patch("encrypted_radio.packet_audio._header", side_effect=oversized):
            invalid = [*encoder.feed("INVALID"), *encoder.flush()]
        valid = [*encoder.feed("LATER"), *encoder.finish()]
        result, decoder = decode(np.concatenate([*invalid, *valid]))
        self.assertNotIn("INVALID", result)
        self.assertTrue(result.endswith("LATER"))
        self.assertTrue(decoder.complete)
        self.assertTrue(decoder.diagnostics)
        self.assertLess(len(decoder._metrics), 300)

    def test_lost_end_truncation_and_acquired_packet_recovery(self):
        encoder = AFSKEncoder()
        data = np.concatenate([*encoder.feed("KEEP"), *encoder.flush()])
        end = np.concatenate(list(encoder.finish()))
        result, decoder = decode(data)
        self.assertTrue(result.startswith("KEEP"))
        self.assertIn("missing audiolink end", " ".join(decoder.diagnostics))
        result, decoder = decode(np.concatenate([data, end[:-4800]]))
        self.assertTrue(result.startswith("KEEP"))
        self.assertFalse(decoder.complete)
        self.assertTrue(decoder.diagnostics)
        # Truncate inside an acquired large packet, then immediately append a
        # later short packet and end. The EOF parser must still find both.
        encoder = AFSKEncoder(AFSKSettings(packet_size=256))
        large = np.concatenate([*encoder.feed("X" * 256), *encoder.flush()])
        later = np.concatenate([*encoder.feed("LATER"), *encoder.finish()])
        cut = round((.2 + (len(TRAINING) + len(SYNC) + HEADER_BITS + 80) / 1200) * 48000)
        result, decoder = decode(np.concatenate([large[:cut], later]))
        self.assertNotIn("X", result)
        self.assertTrue(result.endswith("LATER"))
        self.assertTrue(decoder.complete)
        self.assertTrue(decoder.diagnostics)

    def test_discontinuity_reports_and_recovers_checked_but_raw_stops(self):
        decoder = AFSKDecoder()
        self.assertEqual(decoder.discontinuity("sample loss"), "?")
        self.assertEqual(decoder.feed(synthesize("RECOVER")) + decoder.finish(), "RECOVER")
        self.assertEqual(decoder.error_count, 1)
        with self.assertRaisesRegex(AudioError, "sample loss"):
            AFSKDecoder(profile="raw").discontinuity("sample loss")

    def test_more_than_64_complete_sessions_remain_usable(self):
        # Exercise bounded replay tracking through actual PCM, with short guards.
        decoder = AFSKDecoder()
        output = []
        for _ in range(66):
            output.append(decoder.feed(synthesize("A", AFSKSettings(lead_ms=0, tail_ms=0))))
        output.append(decoder.finish())
        self.assertEqual("".join(output), "A" * 66)
        self.assertFalse(decoder.diagnostics)
        self.assertLessEqual(len(decoder._seen_sessions), 64)

    def test_reproducible_voice_band_dsp_matrix(self):
        text = bytes(np.random.default_rng(43).integers(0, 128, 393, dtype=np.uint8)).decode("ascii")
        for rate in (44100, 48000):
            settings = AFSKSettings(sample_rate=rate)
            clean = synthesize(text, settings, session=b"AFSKtest")
            filtered = band_filter(clean, rate)
            deemphasized = signal.sosfilt(signal.butter(1, 1000, fs=rate, output="sos"), filtered)
            limited = np.clip(deemphasized, -.2, .2)
            combined = noise_at_snr(limited, rate)
            cases = {
                "clean": clean,
                "voice_band": filtered,
                "band_noise_10db": noise_at_snr(filtered, rate),
                "deemphasis_1khz": deemphasized,
                "clip_0.2": np.clip(filtered, -.2, .2),
                "combined": combined,
                "clock_minus1000ppm": signal.resample_poly(filtered, 999, 1000),
                "clock_plus1000ppm": signal.resample_poly(filtered, 1001, 1000),
                "combined_minus1000ppm": signal.resample_poly(combined, 999, 1000),
                "combined_plus1000ppm": signal.resample_poly(combined, 1001, 1000),
                # Startup clipping within the key-up guard, ending within tail.
                "clipped_guards": filtered[round(.15 * rate):-round(.025 * rate)],
            }
            for name, pcm in cases.items():
                with self.subTest(rate=rate, case=name):
                    result, decoder = decode(pcm, rate)
                    self.assertEqual(result, text)
                    self.assertTrue(decoder.complete)
                    self.assertEqual(decoder.diagnostics, [])
        # Off-grid clock errors at the largest supported payload exercise the
        # acquisition search rather than only its exact trial rates.
        settings = AFSKSettings(packet_size=256)
        source = band_filter(synthesize(text, settings, session=b"AFSKtest"), 48000)
        for ratio in (9993 / 10000, 10007 / 10000):
            pcm = np.interp(np.arange(0, len(source) - 1, 1 / ratio), np.arange(len(source)), source)
            result, decoder = decode(pcm)
            self.assertEqual(result, text)
            self.assertFalse(decoder.diagnostics)


class AudioLinkCLITests(unittest.TestCase):
    def test_wav_helpers_and_real_cli_batch_file_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "packet.wav"
            source = Path(directory) / "input.txt"
            text = "Mixed ASCII\nwith punctuation!? and + escapes."
            source.write_text(text, encoding="ascii")
            stats = write_wav(target, text, AFSKSettings(sample_rate=44100))
            self.assertEqual(decode_wav(target), (text, []))
            with wave.open(str(target)) as wav:
                self.assertAlmostEqual(stats["duration"], wav.getnframes() / wav.getframerate())
            for extra, stdin in ((["--text", text], None), (["--input", str(source)], None), ([], text.encode("ascii"))):
                tx = subprocess.run([sys.executable, "-m", "encrypted_radio.audiolink_cli", "tx", "--output-wav", str(target), *extra], input=stdin, capture_output=True)
                self.assertEqual(tx.returncode, 0, tx.stderr)
                self.assertEqual(tx.stdout, b"")
                rx = subprocess.run([sys.executable, "-m", "encrypted_radio.audiolink_cli", "rx", "--input-wav", str(target)], capture_output=True)
                self.assertEqual(rx.returncode, 0, rx.stderr)
                self.assertEqual(rx.stdout, text.encode("ascii"))

    def test_cli_integrity_failure_and_invalid_or_unavailable_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "incomplete.wav"
            encoder = AFSKEncoder()
            pcm = np.concatenate([*encoder.feed("PART"), *encoder.flush()])
            with wave.open(str(target), "wb") as wav:
                wav.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                wav.writeframes((pcm * 32767).astype("<i2").tobytes())
            result = subprocess.run([sys.executable, "-m", "encrypted_radio.audiolink_cli", "rx", "--input-wav", str(target)], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"PART?")
            self.assertIn(b"missing audiolink end", result.stderr)
        output = io.StringIO()
        with redirect_stderr(output), patch("encrypted_radio.live_audio.transmit", side_effect=AudioError("unavailable device")):
            self.assertEqual(audiolink_cli.main(["tx", "--text", "TEST"]), 1)
        self.assertIn("unavailable device", output.getvalue())
        with redirect_stderr(io.StringIO()):
            self.assertEqual(audiolink_cli.main(["tx", "--text", "TEST", "--idle-seconds", "nan"]), 1)

    def test_open_stdin_idle_flush_is_audible_before_eof(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "stream.wav"
            process = subprocess.Popen(
                [sys.executable, "-m", "encrypted_radio.audiolink_cli", "tx", "--idle-seconds", ".05", "--output-wav", str(target)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                process.stdin.write(b"PART")
                process.stdin.flush()
                # A WAV writer may retain up to one filesystem buffer, but the
                # packet's payload is available before its silent tail finishes.
                required = 44 + round((estimate_duration("PART", finish=False) - .05) * 48000) * 2
                deadline = time.monotonic() + 10
                while (not target.exists() or target.stat().st_size < required) and time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(f"transmitter exited early: {process.stderr.read()!r}")
                    time.sleep(.02)
                self.assertTrue(target.exists())
                self.assertGreaterEqual(target.stat().st_size, required)
                self.assertIsNone(process.poll())  # stdin is still open.
                raw = target.read_bytes()[44:]
                pcm = np.frombuffer(raw[:len(raw) // 2 * 2], dtype="<i2").astype(np.float32) / 32768
                self.assertEqual(AFSKDecoder().feed(pcm), "PART")
                process.stdin.write(b"NEXT")
                process.stdin.close()
                process.stdin = None
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual(stdout, b"")
                self.assertEqual(decode_wav(target), ("PARTNEXT", []))
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def test_broken_output_pipe_exits_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "source.wav"
            write_wav(target, "PAYLOAD")
            process = subprocess.Popen(
                [sys.executable, "-m", "encrypted_radio.audiolink_cli", "rx", "--input-wav", str(target)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            process.stdout.close()
            process.wait(timeout=10)
            diagnostic = process.stderr.read()
            process.stderr.close()
            self.assertEqual(process.returncode, 0, diagnostic)
            self.assertNotIn(b"Traceback", diagnostic)

    def test_streaming_idle_flush_and_device_enumeration(self):
        args = audiolink_cli._parser().parse_args(["tx"])
        encoder = AFSKEncoder()
        with patch("encrypted_radio.audiolink_cli.iter_chunks", return_value=iter([b"PART", None, b"NEXT"])):
            pcm = np.concatenate(list(audiolink_cli._chunks(args, encoder)))
        result, decoder = decode(pcm)
        self.assertEqual(result, "PARTNEXT")
        self.assertEqual(encoder._sequence, 3)  # Two data packets and explicit end.
        self.assertFalse(decoder.diagnostics)
        output = io.StringIO()
        with patch("encrypted_radio.live_audio.devices", return_value="device listing"), redirect_stdout(output):
            self.assertEqual(audiolink_cli.main(["devices"]), 0)
        self.assertIn("device listing", output.getvalue())


if __name__ == "__main__":
    unittest.main()
