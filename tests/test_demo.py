"""End-to-end acceptance: measured decoder output, loss recovery and CLI status."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from encrypted_radio.demo import DEFAULT_TEXT, LOSS_TEXT, run_roundtrip


class DemoTests(unittest.TestCase):
    def test_clean_real_audio_roundtrip_and_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = run_roundtrip(DEFAULT_TEXT, output_dir=output)
            self.assertTrue(result["success"], result["errors"])
            self.assertTrue(result["matched"])
            self.assertEqual(result["received_symbols"], result["ciphertext"])
            self.assertEqual((output / "recovered.txt").read_bytes(), DEFAULT_TEXT)
            self.assertGreater((output / "transmission.wav").stat().st_size, 44)
            self.assertTrue(json.loads((output / "report.json").read_text())["success"])

    def test_pcm_noise_and_loss_scenarios(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            noisy = run_roundtrip(DEFAULT_TEXT, scenario="noisy", output_dir=output / "noisy")
            self.assertTrue(noisy["success"], noisy["errors"])
            lost = run_roundtrip(LOSS_TEXT, scenario="lost-block", output_dir=output / "loss")
            self.assertTrue(lost["success"], lost)
            self.assertFalse(lost["matched"])
            self.assertTrue(lost["errors"])
            self.assertEqual(lost["recovered"].encode(), LOSS_TEXT[:16] + LOSS_TEXT[32:])
            self.assertTrue(lost["pcm_segments"][1]["removed"])
            self.assertNotEqual(lost["received_symbols"], lost["ciphertext"])

    def test_loss_recovery_without_end_frame_is_not_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def incomplete_receive(*args, **kwargs):
                # Preserve the expected recovered bytes while losing both the
                # intentional data block and the separately required end marker.
                frames = re.findall(r"VVV\([A-Z2-7]+\)", (output / "ciphertext.txt").read_text())
                return "".join(frame for index, frame in enumerate(frames[:-1]) if index != 1), []

            with patch("encrypted_radio.audio.decode_wav", side_effect=incomplete_receive):
                result = run_roundtrip(LOSS_TEXT, scenario="lost-block", output_dir=output)
            self.assertEqual(result["recovered"].encode(), LOSS_TEXT[:16] + LOSS_TEXT[32:])
            self.assertFalse(result["complete"])
            self.assertFalse(result["success"])
            self.assertIn("missing session end frame", result["errors"])

    def test_decoder_output_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("encrypted_radio.audio.decode_wav", return_value=("", ["injected decoder failure"])) as decode:
                result = run_roundtrip(DEFAULT_TEXT, output_dir=Path(directory))
            decode.assert_called_once()
            self.assertFalse(result["success"])
            self.assertEqual(result["recovered"], "")
            self.assertIn("failed", result["verification"])

    def test_raw_and_text(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode, message in [("raw", b"A+a!\n"), ("text", b"  hello \n world  ")]:
                with self.subTest(mode=mode):
                    result = run_roundtrip(message, mode=mode, output_dir=Path(directory) / mode,
                                           rx_frequency=700, rx_wpm=20)
                    self.assertTrue(result["success"], result["errors"])

    def test_cli_success_and_invalid_loss_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, "-m", "encrypted_radio.demo", "roundtrip", "--output-dir", directory]
            success = subprocess.run(command + ["--mode", "text", "--text", "HELLO", "--rx-wpm", "20"], capture_output=True)
            self.assertEqual(success.returncode, 0, success.stderr.decode())
            self.assertTrue(json.loads(success.stdout)["success"])
            failure = subprocess.run(command + ["--scenario", "lost-block", "--text", "short"], capture_output=True)
            self.assertEqual(failure.returncode, 2)
            self.assertIn(b"at least 33", failure.stderr)
            mismatch = subprocess.run(command + ["--mode", "text", "--text", "HELLO", "--rx-frequency", "1200", "--rx-wpm", "20"], capture_output=True)
            self.assertEqual(mismatch.returncode, 1, mismatch.stderr.decode())
            self.assertFalse(json.loads(mismatch.stdout)["success"])


if __name__ == "__main__":
    unittest.main()
