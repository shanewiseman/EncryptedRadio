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
from .codec import TEXT_ENCODINGS
from . import pipeline

DEFAULT_TEXT = b"Meet at 09:30!\n"
LOSS_TEXT = b"First block kept. Second block lost. Later blocks recover!\n"


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("demonstration cancelled")


def _write_pcm(path, segments, settings, omitted=None, cancel_event=None, transport="morselink"):
    """Write real encoder output, optionally cutting one whole frame's PCM span."""
    import numpy as np
    boundaries = []
    cursor = 0
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(settings.sample_rate)
        packet_encoder = pipeline.audio_encoder(transport, settings, segments[0][1]) if transport == "audiolink" else None
        for index, (text, profile) in enumerate(segments):
            encoder = packet_encoder or pipeline.audio_encoder(transport, settings, profile)
            start = cursor
            for chunks in (encoder.feed(text), encoder.flush() if packet_encoder else encoder.finish()):
                for pcm in chunks:
                    _check_cancel(cancel_event)
                    cursor += len(pcm)
                    if index != omitted:
                        output.writeframesraw((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
            boundaries.append({"frame": index, "start_sample": start,
                               "end_sample": cursor, "removed": index == omitted})
        if packet_encoder is not None:
            start = cursor
            for pcm in packet_encoder.finish():
                _check_cancel(cancel_event)
                cursor += len(pcm)
                output.writeframesraw((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
            boundaries.append({"frame": "transport-end", "start_sample": start,
                               "end_sample": cursor, "removed": False})
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
                  rx_frequency=None, rx_wpm=None, max_duration_s=None, cancel_event=None,
                  cipher_name="rotorcrypt", transport="morselink", text_encoding=None) -> dict:
    """Encrypt, render PCM, decode PCM and decrypt. Every result is measured.

    A loss demo uses 16-byte blocks and removes the second data frame's actual
    PCM. Its success condition is explicitly different from an intact round trip.
    """
    from .audio import iter_wav

    text.decode("ascii")
    pipeline.validate_selection(cipher_name, transport)
    text_encoding = pipeline.resolve_text_encoding(mode, text_encoding)
    if transport == "audiolink" and (rx_frequency is not None or rx_wpm is not None):
        raise ValueError("Morse receiver pitch/speed overrides do not apply to audiolink.")
    _check_cancel(cancel_event)
    if mode not in {"checked", "raw", "text"} or scenario not in {"clean", "noisy", "lost-block"}:
        raise ValueError("unknown mode or scenario")
    if scenario == "lost-block" and (mode != "checked" or len(text) <= 32):
        raise ValueError("lost-block needs checked mode and at least 33 plaintext bytes")
    machine = machine or load_machine()
    key = key or pipeline.demo_key(cipher_name, machine)
    settings = settings or pipeline.audio_settings(transport)
    audio = pipeline.transport_module(transport)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if scenario == "lost-block":
        block_size = 16
    ciphertext = pipeline.encrypt(text, machine, key, cipher_name=cipher_name, mode=mode,
                                  block_size=block_size, text_encoding=text_encoding)
    frames = re.findall(r"VVV\([A-Z2-7]+\)", ciphertext) if scenario == "lost-block" else [ciphertext]
    profile = mode
    omitted = 1 if scenario == "lost-block" else None
    duration = sum(audio.estimate_duration(frame, settings, profile) for index, frame in enumerate(frames) if index != omitted)
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
            boundaries = _write_pcm(clean, [(frame, profile) for frame in frames], settings, cancel_event=cancel_event, transport=transport)
            _add_noise(clean, wav_path, cancel_event=cancel_event)
    else:
        boundaries = _write_pcm(wav_path, [(frame, profile) for frame in frames], settings, omitted, cancel_event, transport)
    if cancel_event is None:
        overrides = {"frequency": rx_frequency, "wpm": rx_wpm} if transport == "morselink" else {}
        received, diagnostics = audio.decode_wav(wav_path, profile=profile, **overrides)
    else:
        decoder = pipeline.audio_decoder(transport, settings.sample_rate, profile, rx_frequency, rx_wpm)
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
        decoded = pipeline.decrypt(received, machine, key, cipher_name=cipher_name, mode=mode,
                                   text_encoding=text_encoding)
        recovered, errors, complete = decoded.plaintext, list(diagnostics) + decoded.errors, decoded.complete
        expected = text[:16] + text[32:] if scenario == "lost-block" else text
    with wave.open(str(wav_path), "rb") as recording:
        duration = recording.getnframes() / recording.getframerate()
    success = complete and recovered == expected and (bool(errors) if omitted is not None else not errors)
    result = {"input": text.decode("ascii"), "ciphertext": ciphertext,
              "received_symbols": received, "recovered": recovered.decode("ascii"),
              "matched": recovered == text, "success": success, "complete": complete,
              "errors": errors, "duration": duration, "wav": paths["wav"],
              "scenario": scenario, "mode": mode, "cipher": cipher_name, "transport": transport,
              "text_encoding": text_encoding,
              "expected": expected.decode("ascii"),
              "paths": paths, "block_size": block_size, "sample_rate": settings.sample_rate,
              "frequency": getattr(settings, "frequency", None), "wpm": getattr(settings, "wpm", None),
              "baud": getattr(settings, "baud", None),
              "pcm_segments": boundaries, "decoder": ("encrypted_radio.packet_audio.AFSKDecoder" if transport == "audiolink" else "encrypted_radio.audio.MorseDecoder"),
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
    run.add_argument("--cipher", choices=pipeline.CIPHERS, default="rotorcrypt")
    run.add_argument("--transport", choices=pipeline.TRANSPORTS, default="morselink")
    encoding = run.add_mutually_exclusive_group()
    encoding.add_argument("--text-encoding", choices=TEXT_ENCODINGS,
                          help="exact-case encoding (default: lowercase-first in cipher modes; ascii aliases uppercase-first)")
    encoding.add_argument("--uppercase-first", dest="text_encoding", action="store_const", const="uppercase-first",
                          help="use legacy uppercase-first encoding at both ends")
    run.add_argument("--scenario", choices=["clean", "noisy", "lost-block"], default="clean")
    run.add_argument("--output-dir", type=Path, default=Path("tmp/demo"))
    run.add_argument("--machine", type=Path)
    run.add_argument("--key", type=Path)
    run.add_argument("--frequency", type=float, help="Morse tone in Hz (default: 700)")
    run.add_argument("--wpm", type=float, help="Morse speed (default: 20 WPM)")
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
        machine = load_machine(args.machine)
        if args.transport == "audiolink" and any(value is not None for value in
                                               (args.frequency, args.wpm, args.rx_frequency, args.rx_wpm)):
            raise ValueError("Morse pitch/speed options do not apply to audiolink's fixed 1200/2200 Hz modem.")
        if args.cipher == "sealcrypt":
            from .seal import load_key as load_seal_key
            key = load_seal_key(args.key) if args.key else pipeline.demo_key(args.cipher, machine)
        else:
            key = load_key(args.key, machine)
        text = (args.text.encode("ascii") if args.text is not None else args.input.read_bytes()
                if args.input else LOSS_TEXT if args.scenario == "lost-block" else DEFAULT_TEXT)
        result = run_roundtrip(text, mode=args.mode, scenario=args.scenario, machine=machine, key=key,
                               output_dir=args.output_dir,
                               settings=pipeline.audio_settings(args.transport, sample_rate=args.sample_rate,
                                                                frequency=args.frequency if args.frequency is not None else 700,
                                                                wpm=args.wpm if args.wpm is not None else 20),
                               block_size=args.block_size, rx_frequency=args.rx_frequency, rx_wpm=args.rx_wpm,
                               cipher_name=args.cipher, transport=args.transport, text_encoding=args.text_encoding)
        print(json.dumps({field: result[field] for field in
                          ("success", "matched", "cipher", "transport", "text_encoding", "scenario", "duration", "errors", "verification")}))
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
