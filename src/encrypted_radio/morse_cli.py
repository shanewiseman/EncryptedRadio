"""Half-duplex character/audio command line adapter."""

import argparse
from contextlib import nullcontext
import itertools
import os
import sys
import wave

import numpy as np

from .audio import AudioError, AudioSettings, MorseDecoder, MorseEncoder, iter_wav
from .morse import PROFILES


def _parser():
    parser = argparse.ArgumentParser(prog="morselink", description="Half-duplex ASCII Morse audio transport")
    commands = parser.add_subparsers(dest="command", required=True)
    tx = commands.add_parser("tx", help="read text and transmit tones")
    source = tx.add_mutually_exclusive_group()
    source.add_argument("--text", help="complete ASCII input")
    source.add_argument("--input", help="ASCII input file (default: streaming stdin)")
    tx.add_argument("--output-wav", help="write PCM WAV instead of playing sound")
    rx = commands.add_parser("rx", help="receive tones and write text")
    rx.add_argument("--input-wav", help="read WAV instead of opening microphone")
    for child, speed, frequency in ((tx, 20, 700), (rx, None, None)):
        child.add_argument("--profile", choices=PROFILES, default="checked")
        child.add_argument("--frequency", type=float, default=frequency, help="tone Hz (RX default: auto 400–1200)")
        child.add_argument("--wpm", type=float, default=speed, help="speed (RX default: auto 8–30 WPM)")
        child.add_argument("--sample-rate", type=int, default=48000)
        child.add_argument("--device", help="audio device index or name")
    commands.add_parser("devices", help="list available audio devices without recording")
    return parser


def _texts(args):
    if args.text is not None:
        args.text.encode("ascii")
        yield args.text
        return
    with open(args.input, "rb") if args.input else nullcontext(sys.stdin.buffer) as source:
        read = getattr(source, "read1", source.read)
        while data := read(4096):
            yield data.decode("ascii")


def _chunks(args, encoder):
    for text in _texts(args):
        yield from encoder.feed(text)
    yield from encoder.finish()


def _emit(text):
    if text:
        sys.stdout.write(text)
        sys.stdout.flush()


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "devices":
            from .live_audio import devices
            print(devices())
            return 0
        device = int(args.device) if args.device and args.device.isdecimal() else args.device
        if args.command == "tx":
            settings = AudioSettings(args.sample_rate, args.frequency, args.wpm)
            encoder = MorseEncoder(settings, args.profile)
            chunks = iter(_chunks(args, encoder))
            # Validate the first available input before opening an audio device.
            initial = next(chunks, None)
            chunks = itertools.chain(() if initial is None else (initial,), chunks)
            if args.output_wav:
                with wave.open(args.output_wav, "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(settings.sample_rate)
                    for chunk in chunks:
                        output.writeframesraw((np.clip(chunk, -1, 1) * 32767).astype("<i2").tobytes())
            else:
                from .live_audio import transmit
                transmit(chunks, settings.sample_rate, device)
            return 0
        if args.input_wav:
            with wave.open(args.input_wav, "rb") as source:
                rate = source.getframerate()
            chunks = iter_wav(args.input_wav)
        else:
            from .live_audio import receive
            rate = args.sample_rate
            chunks = receive(rate, device)
        decoder = MorseDecoder(rate, args.profile, args.frequency, args.wpm)
        reported = 0
        try:
            for chunk in chunks:
                _emit(decoder.feed(chunk))
                for diagnostic in decoder.diagnostics[reported:]:
                    print(f"morselink: {diagnostic}", file=sys.stderr)
                reported = len(decoder.diagnostics)
        except AudioError as error:
            _emit(decoder.discontinuity(str(error)))
            raise
        finally:
            chunks.close()
        _emit(decoder.finish())
        for diagnostic in decoder.diagnostics[reported:]:
            print(f"morselink: {diagnostic}", file=sys.stderr)
        return 1 if decoder.diagnostics else 0
    except BrokenPipeError:
        # Prevent a second exception during interpreter stdout finalization.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, wave.Error) as error:
        print(f"morselink: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
