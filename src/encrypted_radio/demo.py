"""Reproducible demos that go through the real PCM decoder, without audio hardware."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
import wave

from .config import load_key, load_machine

DEFAULT_TEXT = b"Meet at 09:30!\n"
LOSS_TEXT = b"First block kept. Second block lost. Later blocks recover!\n"


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("demonstration cancelled")


def _write_pcm(path, segments, settings, omitted=None, cancel_event=None):
    """Write real encoder output, optionally cutting one whole frame's PCM span."""
    import numpy as np
    from .audio import MorseEncoder

    boundaries = []
    cursor = 0
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(settings.sample_rate)
        for index, (text, profile) in enumerate(segments):
            encoder = MorseEncoder(settings, profile=profile)
            start = cursor
            for chunks in (encoder.feed(text), encoder.finish()):
                for pcm in chunks:
                    _check_cancel(cancel_event)
                    cursor += len(pcm)
                    if index != omitted:
                        output.writeframesraw((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
            boundaries.append({"frame": index, "start_sample": start,
                               "end_sample": cursor, "removed": index == omitted})
    return boundaries


def _add_noise(source: Path, destination: Path, snr_db: float = 10.0, cancel_event=None):
    """Add seeded 300–3000 Hz noise at the measured whole-recording SNR in chunks."""
    import numpy as np
    from scipy import signal

    total_energy = 0.0
    count = 0
    with wave.open(str(source), "rb") as audio:
        rate = audio.getframerate()
        while data := audio.readframes(65536):
            _check_cancel(cancel_event)
            pcm = np.frombuffer(data, dtype="<i2").astype(np.float64) / 32768
            total_energy += float(pcm @ pcm)
            count += len(pcm)
    sos = signal.butter(4, [300, min(3000, rate * .45)], btype="bandpass", fs=rate, output="sos")
    _, response = signal.sosfreqz(sos, worN=16384)
    noise_gain = float(np.mean(abs(response) ** 2)) ** .5
    noise_scale = (total_energy / max(count, 1)) ** .5 / (10 ** (snr_db / 20)) / noise_gain
    rng = np.random.default_rng(20261003)
    state = np.zeros((len(sos), 2))
    with wave.open(str(source), "rb") as audio, wave.open(str(destination), "wb") as output:
        output.setparams(audio.getparams())
        while data := audio.readframes(65536):
            _check_cancel(cancel_event)
            pcm = np.frombuffer(data, dtype="<i2").astype(np.float64) / 32768
            noise, state = signal.sosfilt(sos, rng.standard_normal(len(pcm)), zi=state)
            # A common gain avoids clipping while preserving the requested SNR.
            mixed = (pcm + noise * noise_scale) * .7
            output.writeframesraw((np.clip(mixed, -1, 1) * 32767).astype("<i2").tobytes())


def run_roundtrip(text: bytes, *, mode="checked", scenario="clean", machine=None,
                  key=None, output_dir: Path, settings=None, block_size=128,
                  rx_frequency=None, rx_wpm=None, max_duration_s=None, cancel_event=None) -> dict:
    """Encrypt, render PCM, decode PCM and decrypt. Every result is measured.

    A loss demo uses 16-byte blocks and removes the second data frame's actual
    PCM. Its success condition is explicitly different from an intact round trip.
    """
    from .audio import AudioSettings, MorseDecoder, decode_wav, estimate_duration, iter_wav
    from .cipher import decrypt_text, encrypt_bytes

    text.decode("ascii")
    _check_cancel(cancel_event)
    if mode not in {"checked", "raw", "text"} or scenario not in {"clean", "noisy", "lost-block"}:
        raise ValueError("unknown mode or scenario")
    if scenario == "lost-block" and (mode != "checked" or len(text) <= 32):
        raise ValueError("lost-block needs checked mode and at least 33 plaintext bytes")
    machine = machine or load_machine()
    key = key or load_key(machine=machine)
    settings = settings or AudioSettings()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if scenario == "lost-block":
        block_size = 16
    ciphertext = text.decode("ascii") if mode == "text" else encrypt_bytes(
        text, machine, key, mode=mode, block_size=block_size)
    frames = re.findall(r"VVV\([A-Z2-7]+\)", ciphertext) if scenario == "lost-block" else [ciphertext]
    profile = mode
    omitted = 1 if scenario == "lost-block" else None
    duration = sum(estimate_duration(frame, settings, profile) for index, frame in enumerate(frames) if index != omitted)
    if max_duration_s is not None and duration > max_duration_s:
        raise ValueError("This transmission exceeds ten minutes; shorten the message or use the CLI.")
    paths = {"input": "input.txt", "ciphertext": "ciphertext.txt", "wav": "transmission.wav",
             "received_symbols": "received-symbols.txt", "recovered": "recovered.txt", "report": "report.json"}
    (output_dir / paths["input"]).write_bytes(text)
    (output_dir / paths["ciphertext"]).write_bytes(ciphertext.encode("ascii"))
    wav_path = output_dir / paths["wav"]
    if scenario == "noisy":
        with tempfile.TemporaryDirectory(dir=output_dir) as temporary:
            clean = Path(temporary) / "clean.wav"
            boundaries = _write_pcm(clean, [(frame, profile) for frame in frames], settings, cancel_event=cancel_event)
            _add_noise(clean, wav_path, cancel_event=cancel_event)
    else:
        boundaries = _write_pcm(wav_path, [(frame, profile) for frame in frames], settings, omitted, cancel_event)
    if cancel_event is None:
        received, diagnostics = decode_wav(wav_path, profile=profile, frequency=rx_frequency, wpm=rx_wpm)
    else:
        decoder = MorseDecoder(settings.sample_rate, profile, rx_frequency, rx_wpm)
        symbols = []
        for pcm in iter_wav(wav_path):
            _check_cancel(cancel_event)
            symbols.append(decoder.feed(pcm))
        received = "".join(symbols) + decoder.finish()
        diagnostics = decoder.diagnostics
    if mode == "text":
        recovered = received.encode("ascii")
        expected = b" ".join(text.upper().split())
        errors = list(diagnostics)
        complete = not errors
    else:
        decoded = decrypt_text(received, machine, key, mode=mode)
        recovered, errors, complete = decoded.plaintext, list(diagnostics) + decoded.errors, decoded.complete
        expected = text[:16] + text[32:] if scenario == "lost-block" else text
    with wave.open(str(wav_path), "rb") as recording:
        duration = recording.getnframes() / recording.getframerate()
    success = complete and recovered == expected and (bool(errors) if omitted is not None else not errors)
    result = {"input": text.decode("ascii"), "ciphertext": ciphertext,
              "received_symbols": received, "recovered": recovered.decode("ascii"),
              "matched": recovered == text, "success": success, "complete": complete,
              "errors": errors, "duration": duration, "wav": paths["wav"],
              "scenario": scenario, "mode": mode, "expected": expected.decode("ascii"),
              "paths": paths, "block_size": block_size, "sample_rate": settings.sample_rate,
              "frequency": settings.frequency, "wpm": settings.wpm,
              "pcm_segments": boundaries, "decoder": "encrypted_radio.audio.MorseDecoder",
              "noise_snr_db": 10 if scenario == "noisy" else None,
              "verification": ("Verification failed; review errors and recovered output" if not success else
                               "Missing block reported; subsequent plaintext recovered" if omitted is not None else
                               "Recovered output equals expected bytes")}
    (output_dir / paths["received_symbols"]).write_bytes(received.encode("ascii"))
    (output_dir / paths["recovered"]).write_bytes(recovered)
    (output_dir / paths["report"]).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("roundtrip", help="verify the real cipher → WAV → DSP → cipher pipeline")
    source = run.add_mutually_exclusive_group()
    source.add_argument("--text")
    source.add_argument("--input", type=Path)
    run.add_argument("--mode", choices=["checked", "raw", "text"], default="checked")
    run.add_argument("--scenario", choices=["clean", "noisy", "lost-block"], default="clean")
    run.add_argument("--output-dir", type=Path, default=Path("tmp/demo"))
    run.add_argument("--machine", type=Path)
    run.add_argument("--key", type=Path)
    run.add_argument("--frequency", type=float, default=700)
    run.add_argument("--wpm", type=float, default=20)
    run.add_argument("--sample-rate", type=int, default=48000)
    run.add_argument("--rx-frequency", type=float)
    run.add_argument("--rx-wpm", type=float)
    run.add_argument("--block-size", type=int, default=128)
    serve = commands.add_parser("serve", help="start the local browser demo")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from .web import serve as serve_web
            serve_web(host=args.host, port=args.port)
            return 0
        from .audio import AudioSettings
        machine = load_machine(args.machine)
        key = load_key(args.key, machine)
        text = (args.text.encode("ascii") if args.text is not None else args.input.read_bytes()
                if args.input else LOSS_TEXT if args.scenario == "lost-block" else DEFAULT_TEXT)
        result = run_roundtrip(text, mode=args.mode, scenario=args.scenario, machine=machine, key=key,
                               output_dir=args.output_dir,
                               settings=AudioSettings(sample_rate=args.sample_rate, frequency=args.frequency, wpm=args.wpm),
                               block_size=args.block_size, rx_frequency=args.rx_frequency, rx_wpm=args.rx_wpm)
        print(json.dumps({field: result[field] for field in
                          ("success", "matched", "scenario", "duration", "errors", "verification")}))
        print(f"Artifacts: {args.output_dir.resolve()}", file=sys.stderr)
        return 0 if result["success"] else 1
    except BrokenPipeError:
        return 0
    except (ValueError, OSError, ImportError) as error:
        print(f"er-demo: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
