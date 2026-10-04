"""Half-duplex voice-band packet audio command line adapter."""

import argparse
from contextlib import nullcontext
import itertools
import math
import os
import sys
import wave

import numpy as np

from .audio import AudioError, iter_wav
from .morse import PROFILES
from .packet_audio import AFSKDecoder, AFSKEncoder, AFSKSettings
from .streams import iter_chunks


def _parser():
    parser = argparse.ArgumentParser(prog="audiolink", description="Half-duplex 1200 bit/s voice-band packet AFSK transport")
    commands = parser.add_subparsers(dest="command", required=True)
    tx = commands.add_parser("tx", help="read ASCII and transmit packet audio")
    source = tx.add_mutually_exclusive_group()
    source.add_argument("--text", help="complete ASCII input")
    source.add_argument("--input", help="ASCII input file (default: streaming stdin)")
    tx.add_argument("--output-wav", help="write mono PCM WAV instead of playing sound")
    tx.add_argument("--packet-size", type=int, default=128, help="ASCII bytes per data packet, 1–256 (default: 128)")
    tx.add_argument("--lead-ms", type=float, default=200, help="mark-tone key-up lead per packet (default: 200 ms)")
    tx.add_argument("--tail-ms", type=float, default=50, help="silent tail per packet (default: 50 ms)")
    tx.add_argument("--idle-seconds", type=float, default=.25, help="flush a partial packet after idle input (default: .25 s)")
    rx = commands.add_parser("rx", help="receive packet audio and write ASCII")
    rx.add_argument("--input-wav", help="read WAV instead of opening microphone")
    for child in (tx, rx):
        child.add_argument("--profile", choices=PROFILES, default="checked")
        child.add_argument("--sample-rate", type=int, default=48000, help="live audio rate (WAV reception uses the file rate)")
        child.add_argument("--device", help="audio device index or name")
    commands.add_parser("devices", help="list available audio devices without recording")
    return parser


def _chunks(args, encoder):
    if args.text is not None:
        yield from encoder.feed(args.text)
    else:
        with open(args.input, "rb") if args.input else nullcontext(sys.stdin.buffer) as source:
            for data in iter_chunks(source, args.idle_seconds):
                if data is None:
                    yield from encoder.flush()
                else:
                    yield from encoder.feed(data.decode("ascii"))
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
            if not math.isfinite(args.idle_seconds) or args.idle_seconds <= 0:
                raise ValueError("idle-seconds must be positive and finite")
            settings = AFSKSettings(sample_rate=args.sample_rate, packet_size=args.packet_size,
                                    lead_ms=args.lead_ms, tail_ms=args.tail_ms)
            encoder = AFSKEncoder(settings, args.profile)
            chunks = iter(_chunks(args, encoder))
            # Input/configuration errors precede device opening when possible.
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
        decoder = AFSKDecoder(rate, args.profile)
        reported = 0
        try:
            for chunk in chunks:
                _emit(decoder.feed(chunk))
                for diagnostic in decoder.diagnostics[reported:]:
                    print(f"audiolink: {diagnostic}", file=sys.stderr)
                reported = len(decoder.diagnostics)
        except AudioError as error:
            _emit(decoder.discontinuity(str(error)))
            raise
        finally:
            chunks.close()
        _emit(decoder.finish())
        for diagnostic in decoder.diagnostics[reported:]:
            print(f"audiolink: {diagnostic}", file=sys.stderr)
        return 1 if decoder.error_count else 0
    except BrokenPipeError:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, wave.Error) as error:
        print(f"audiolink: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
