"""Independent signal fixtures exercise the receiver without encoder metadata."""

from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import numpy as np
from scipy import signal

from encrypted_radio.audio import AudioError, AudioSettings, MorseDecoder, MorseEncoder, decode_wav, estimate_duration, write_wav
from encrypted_radio.morse import MORSE


def keyed_signal(text, rate, pitch, speed, *, jitter=0, noise_db=None, seed=218):
    """Independent hard-keyed oscillator, unlike encoder's ramped oscillator."""
    rng = np.random.default_rng(seed)
    pieces = []
    dot = rate * 1.2 / speed
    for character in text:
        for index, symbol in enumerate(MORSE[character]):
            if index:
                pieces.append(np.zeros(round(dot * rng.uniform(1 - jitter, 1 + jitter))))
            count = round(dot * (1 if symbol == "." else 3) * rng.uniform(1 - jitter, 1 + jitter))
            pieces.append(0.65 * np.sin(2 * np.pi * pitch * np.arange(count) / rate))
        pieces.append(np.zeros(round(3 * dot * rng.uniform(1 - jitter, 1 + jitter))))
    pcm = np.concatenate(pieces)
    if noise_db is not None:
        noise = signal.sosfilt(signal.butter(4, [350, 1250], fs=rate, btype="bandpass", output="sos"), rng.normal(size=len(pcm)))
        noise *= np.sqrt(np.mean(pcm * pcm) / 10 ** (noise_db / 10)) / np.std(noise)
        pcm += noise
    return pcm.astype(np.float32)


class MorseTests(unittest.TestCase):
    def test_reference_patterns(self):
        self.assertEqual(MORSE["S"], "...")
        self.assertEqual(MORSE["O"], "---")
        self.assertEqual(MORSE["@"], ".--.-.")
        self.assertEqual(len(MORSE), 49)
        self.assertEqual(len(set(MORSE.values())), 49)

    def test_every_character_and_arbitrary_chunks(self):
        text = "VVV" + "".join(MORSE)
        encoder = MorseEncoder()
        pcm = np.concatenate([*encoder.feed(text), *encoder.finish()])
        decoder = MorseDecoder()
        output = []
        for chunk in np.array_split(pcm, 1703):
            output.append(decoder.feed(chunk))
        output.append(decoder.finish())
        self.assertEqual("".join(output), text)
        self.assertEqual(decoder.diagnostics, [])
        self.assertAlmostEqual(decoder.frequency, 700, delta=5)
        self.assertAlmostEqual(decoder.wpm, 20, delta=1)

    def test_mandatory_noise_and_jitter_matrix(self):
        # Eighteen combinations spanning the supported endpoints plus center,
        # with independently generated ±20% key timing and 10 dB band noise.
        expected = "VVV(ABC234)"
        for rate in (44100, 48000):
            for pitch in (400, 700, 1200):
                for speed in (8, 20, 30):
                    with self.subTest(rate=rate, pitch=pitch, speed=speed):
                        pcm = keyed_signal(expected, rate, pitch, speed, jitter=0.2, noise_db=10)
                        decoder = MorseDecoder(rate)
                        actual = decoder.feed(pcm) + decoder.finish()
                        self.assertEqual(actual, expected)
                        self.assertEqual(decoder.diagnostics, [])

    def test_auto_acquisition_across_arbitrary_startup_phase(self):
        expected = "VVV(ABC234)"
        for pitch in (400, 700, 1200):
            encoder = MorseEncoder(AudioSettings(frequency=pitch, wpm=30))
            waveform = np.concatenate([*encoder.feed(expected), *encoder.finish()])
            # Move the first dot across the receiver's 50 ms FFT window. Use
            # chunks incommensurate with both FFT and envelope window lengths.
            for offset_ms in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 49):
                with self.subTest(frequency=pitch, offset_ms=offset_ms):
                    pcm = np.concatenate([np.zeros(offset_ms * 48, np.float32), waveform])
                    decoder = MorseDecoder()
                    output = [decoder.feed(pcm[start:start + 7137]) for start in range(0, len(pcm), 7137)]
                    output.append(decoder.finish())
                    self.assertEqual("".join(output), expected)
                    self.assertEqual(decoder.diagnostics, [])

    def test_encoder_duration_and_bounded_chunks(self):
        for rate in (44100, 48000):
            settings = AudioSettings(rate, 600, 17)
            encoder = MorseEncoder(settings, "text")
            chunks = [*encoder.feed("  Hello\t  World\n"), *encoder.finish()]
            self.assertTrue(all(chunk.dtype == np.float32 and len(chunk) <= rate * 0.02 for chunk in chunks))
            self.assertAlmostEqual(sum(map(len, chunks)) / rate, estimate_duration("  Hello\t  World\n", settings, "text"))

    def test_text_words_and_whitespace(self):
        encoder = MorseEncoder(profile="text")
        pcm = np.concatenate([*encoder.feed("  Hello  \n"), *encoder.feed(" world\n  "), *encoder.finish()])
        decoder = MorseDecoder(profile="text")
        self.assertEqual(decoder.feed(pcm) + decoder.finish(), "HELLO WORLD")

    def test_silence_noise_and_long_pause(self):
        decoder = MorseDecoder(frequency=700)
        self.assertEqual(decoder.feed(np.zeros(480000 * 11)) + decoder.finish(), "")
        self.assertEqual(decoder.diagnostics, [])
        for seed in (0, 1, 2):
            noise = signal.sosfilt(signal.butter(4, [400, 1200], fs=48000, btype="bandpass", output="sos"), np.random.default_rng(seed).normal(size=480000)) * 0.1
            decoder = MorseDecoder()
            self.assertEqual(decoder.feed(np.zeros(480000)) + decoder.feed(noise) + decoder.finish(), "")
            self.assertEqual(decoder.diagnostics, [])
        encoder = MorseEncoder()
        first = np.concatenate(list(encoder.feed("VVVABC")))
        second = np.concatenate([*encoder.feed("DEF"), *encoder.finish()])
        decoder = MorseDecoder()
        self.assertEqual(decoder.feed(first) + decoder.feed(np.zeros(480000)) + decoder.feed(second) + decoder.finish(), "VVVABCDEF")

    def test_ambiguous_timing_and_manual_override(self):
        pcm = keyed_signal("E", 48000, 700, 20)
        decoder = MorseDecoder()
        self.assertEqual(decoder.feed(pcm) + decoder.finish(), "?")
        self.assertIn("ambiguous", decoder.diagnostics[0])
        decoder = MorseDecoder(wpm=20)
        self.assertEqual(decoder.feed(pcm) + decoder.finish(), "E")
        decoder = MorseDecoder(wpm=20, frequency=700)
        self.assertEqual(decoder.feed(pcm * 0.01) + decoder.finish(), "E")

    def test_errors_are_explicit_and_raw_is_fatal(self):
        for profile in ("checked", "text"):
            decoder = MorseDecoder(profile=profile)
            self.assertEqual(decoder.discontinuity("sample loss"), "?")
            self.assertEqual(decoder.diagnostics, ["sample loss"])
        with self.assertRaises(AudioError):
            MorseDecoder(profile="raw").discontinuity("sample loss")
        decoder = MorseDecoder()
        for _ in range(200):
            decoder.discontinuity("sample loss")
        self.assertEqual(decoder.error_count, 200)
        self.assertEqual(len(decoder.diagnostics), 128)
        for text in ("~", "é", "lowercase", " "):
            with self.assertRaises(ValueError):
                list(MorseEncoder().feed(text))
        with self.assertRaises(ValueError):
            MorseDecoder().feed(np.array([float("nan")]))
        with self.assertRaises(ValueError):
            AudioSettings(frequency=float("inf"))
        for options in ({"wpm": 0}, {"frequency": 0}, {"profile": "invalid"}):
            with self.assertRaises(ValueError):
                MorseDecoder(**options)

    def test_wav_roundtrip_and_sample_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "morse.wav"
            settings = AudioSettings(44100, 800, 30)
            metadata = write_wav(path, "VVV(HELLO123)", settings)
            with wave.open(str(path)) as wav:
                self.assertEqual(wav.getnframes(), metadata["samples"])
                self.assertEqual(wav.getframerate(), 44100)
            self.assertEqual(decode_wav(path), ("VVV(HELLO123)", []))

    def test_cli_stream_wav_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "morse.wav")
            process = subprocess.run([sys.executable, "-m", "encrypted_radio.morse_cli", "tx", "--output-wav", path], input=b"VVV(ABC123)", capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            process = subprocess.run([sys.executable, "-m", "encrypted_radio.morse_cli", "rx", "--input-wav", path], capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout, b"VVV(ABC123)")
            process = subprocess.run([sys.executable, "-m", "encrypted_radio.morse_cli", "tx", "--text", "é", "--output-wav", path], capture_output=True)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(process.stdout, b"")

    def test_missing_device_library_is_actionable(self):
        from encrypted_radio import live_audio
        with patch.dict(sys.modules, {"sounddevice": None}):
            with self.assertRaisesRegex(AudioError, "PortAudio"):
                live_audio.devices()

    def test_hardware_overflow_and_cleanup_without_accessing_device(self):
        from encrypted_radio import live_audio
        closed = []

        class Input:
            active = True

            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]

            def __enter__(self):
                for _ in range(101):
                    self.callback(np.zeros((960, 1), np.float32), 960, None, False)
                return self

            def __exit__(self, *args):
                closed.append(True)

        fake = SimpleNamespace(InputStream=Input, PortAudioError=RuntimeError)
        with patch.object(live_audio, "_sounddevice", return_value=fake):
            with self.assertRaisesRegex(AudioError, "queue overflow"):
                next(live_audio.receive())
        self.assertEqual(closed, [True])

    def test_hardware_output_failure_without_accessing_device(self):
        from encrypted_radio import live_audio

        class Output:
            active = True

            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]

            def __enter__(self):
                self.callback(np.zeros((960, 1), np.float32), 960, None, "output underflow")
                return self

            def __exit__(self, *args):
                pass

        fake = SimpleNamespace(OutputStream=Output, PortAudioError=RuntimeError)
        with patch.object(live_audio, "_sounddevice", return_value=fake):
            with self.assertRaisesRegex(AudioError, "playback discontinuity"):
                live_audio.transmit([np.zeros(960, np.float32)])

    def test_paused_transmitter_plays_silence_and_drains_all_samples(self):
        from encrypted_radio import live_audio
        captured = []

        class Output:
            active = True

            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
                self.stopped = threading.Event()

            def __enter__(self):
                def consume():
                    while not self.stopped.is_set():
                        buffer = np.zeros((960, 1), np.float32)
                        self.callback(buffer, 960, None, False)
                        captured.append(buffer.copy())
                        self.stopped.wait(0.005)
                self.thread = threading.Thread(target=consume)
                self.thread.start()
                return self

            def __exit__(self, *args):
                self.stopped.set()
                self.thread.join(timeout=1)

        def producer():
            yield np.ones(100, np.float32)
            # An empty queue while a user pauses at stdin is intentional silence.
            time.sleep(0.030)
            yield np.full(1860, 0.5, np.float32)

        fake = SimpleNamespace(OutputStream=Output, PortAudioError=RuntimeError)
        with patch.object(live_audio, "_sounddevice", return_value=fake):
            live_audio.transmit(producer())
        received = np.concatenate(captured)[:, 0]
        self.assertEqual(np.count_nonzero(received == 1), 100)
        self.assertEqual(np.count_nonzero(received == 0.5), 1860)
        self.assertGreater(np.count_nonzero(received == 0), 960)

    def test_rx_broken_pipe_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "morse.wav"
            write_wav(path, "VVV" + "ABC" * 12)
            process = subprocess.Popen([sys.executable, "-m", "encrypted_radio.morse_cli", "rx", "--input-wav", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertTrue(process.stdout.read(1))
            process.stdout.close()
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertEqual(process.stderr.read(), b"")
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
