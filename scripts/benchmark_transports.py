#!/usr/bin/env python3
"""Measure the same 20-word message through both real, voice-band WAV decoders.

Run with: uv run --locked --extra demo python scripts/benchmark_transports.py
This is a synthetic channel comparison, not a handheld-radio acceptance test.
"""
import argparse
import json
from pathlib import Path
import time
import wave

import numpy as np
from scipy import signal

from encrypted_radio import pipeline, seal
from encrypted_radio.config import load_machine

MESSAGE = b"Meet me at the old bridge tomorrow morning and bring the blue notebook so we can finish our secret project."


def voice_band(source, destination):
    """Apply the same causal third-order 300–3000 Hz bandpass to both transports."""
    with wave.open(str(source), "rb") as recording, wave.open(str(destination), "wb") as output:
        output.setparams(recording.getparams())
        sos = signal.butter(3, [300, 3000], fs=recording.getframerate(), btype="bandpass", output="sos")
        state = np.zeros((len(sos), 2))
        while raw := recording.readframes(65536):
            pcm, state = signal.sosfilt(sos, np.frombuffer(raw, dtype="<i2") / 32768, zi=state)
            output.writeframesraw((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())


def benchmark(directory, ciphertext_path=None):
    directory.mkdir(parents=True, exist_ok=True)
    machine = load_machine()
    # Intentionally public synthetic fixture. Each ciphertext uses a fresh session salt.
    key = seal.SealKey(bytes(range(32)))
    ciphertext = (ciphertext_path.read_text(encoding="ascii") if ciphertext_path else
                  pipeline.encrypt(MESSAGE, machine, key, cipher_name="sealcrypt"))
    verified = pipeline.decrypt(ciphertext, machine, key, cipher_name="sealcrypt")
    if verified.plaintext != MESSAGE or verified.errors or not verified.complete:
        raise ValueError("Replayed ciphertext must be a complete benchmark fixture for the public test key.")
    (directory / "input.txt").write_bytes(MESSAGE)
    (directory / "ciphertext.txt").write_text(ciphertext, encoding="ascii")
    rows = []
    for label, mode, symbols in (("Plain text", "text", MESSAGE.decode("ascii")),
                                 ("Sealcrypt checked", "checked", ciphertext)):
        for transport in pipeline.TRANSPORTS:
            stem = f"{mode}-{transport}"
            clean, filtered = directory / f"{stem}-clean.wav", directory / f"{stem}-voice-band.wav"
            module = pipeline.transport_module(transport)
            settings = pipeline.audio_settings(transport)
            started = time.perf_counter()
            module.write_wav(clean, symbols, settings, profile=mode)
            voice_band(clean, filtered)
            received, errors = module.decode_wav(filtered, profile=mode)
            if mode == "text":
                recovered = received.encode("ascii")
                expected = b" ".join(MESSAGE.upper().split())
            else:
                decoded = pipeline.decrypt(received, machine, key, cipher_name="sealcrypt")
                recovered, expected = decoded.plaintext, MESSAGE
                errors = list(errors) + decoded.errors
                if not decoded.complete:
                    errors.append("Cipher stream did not complete")
            with wave.open(str(filtered), "rb") as recording:
                duration = recording.getnframes() / recording.getframerate()
            symbols_exact = received == (expected.decode("ascii") if mode == "text" else symbols)
            row = {"case": label, "transport": transport, "input_bytes": len(MESSAGE),
                   "symbols": len(symbols), "duration_seconds": duration,
                   "processing_seconds": round(time.perf_counter() - started, 3),
                   "exact": recovered == expected and symbols_exact and not errors,
                   "symbols_exact": symbols_exact, "errors": errors,
                   "wav": str(filtered)}
            rows.append(row)
            print(json.dumps(row), flush=True)
    comparisons = []
    for morse, packet in zip(rows[::2], rows[1::2]):
        comparisons.append({"case": morse["case"], "speedup": morse["duration_seconds"] / packet["duration_seconds"],
                            "time_reduction_percent": 100 * (1 - packet["duration_seconds"] / morse["duration_seconds"])})
    report = {"message": MESSAGE.decode(), "words": len(MESSAGE.split()), "channel": "Synthetic third-order 300–3000 Hz bandpass; no noise or hardware",
              "sample_rate": 48000, "rows": rows, "comparisons": comparisons}
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/audiolink-comparison"))
    parser.add_argument("--ciphertext", type=Path, help="replay a previously saved public benchmark ciphertext for identical Morse timing")
    arguments = parser.parse_args()
    result = benchmark(arguments.output_dir, arguments.ciphertext)
    print(json.dumps(result["comparisons"]))
    raise SystemExit(0 if all(row["exact"] for row in result["rows"]) else 1)
