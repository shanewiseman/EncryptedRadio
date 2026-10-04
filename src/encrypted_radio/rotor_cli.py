"""Pipe-friendly rotorcrypt command line interface."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import os
import select
import sys
from typing import BinaryIO, Iterator

from .cipher import RawDecoder, RawEncoder
from .config import load_key, load_machine
from .framing import CheckedDecoder, CheckedEncoder


def _chunks(stream: BinaryIO, idle_seconds: float | None = None) -> Iterator[bytes | None]:
    """Read available bytes without waiting for a full buffered chunk or a newline."""
    descriptor = stream.fileno()
    while True:
        ready, _, _ = select.select([descriptor], [], [], idle_seconds)
        if not ready:
            yield None
            continue
        data = os.read(descriptor, 4096)
        if not data:
            return
        yield data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experimental Enigma-style ASCII encryption; not modern secure encryption.")
    parser.add_argument("operation", choices=("encrypt", "decrypt"))
    parser.add_argument("--machine", required=True, help="public machine JSON file")
    parser.add_argument("--key", required=True, help="private key JSON file; bundled examples are public")
    parser.add_argument("--mode", choices=("checked", "raw"), default="checked")
    parser.add_argument("--block-size", type=int, default=128)
    parser.add_argument("--idle-seconds", type=float, default=5.0, help="checked encryption idle flush interval (default: 5)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="complete ASCII text")
    source.add_argument("--input", help="input filename; stdin is the default")
    args = parser.parse_args(argv)
    try:
        if not 0 < args.idle_seconds <= 3600:
            raise ValueError("idle seconds must be greater than zero and at most 3600")
        machine = load_machine(args.machine)
        key = load_key(args.key, machine)
        encrypt = args.operation == "encrypt"
        if encrypt:
            operation = CheckedEncoder(machine, key, args.block_size) if args.mode == "checked" else RawEncoder(machine, key)
        else:
            operation = CheckedDecoder(machine, key) if args.mode == "checked" else RawDecoder(machine, key)
        diagnostics = 0

        def emit(value: str | bytes) -> None:
            if value:
                sys.stdout.buffer.write(value.encode("ascii") if isinstance(value, str) else value)
                sys.stdout.buffer.flush()

        def report() -> None:
            nonlocal diagnostics
            errors = getattr(operation, "errors", [])
            for message in errors[diagnostics:]:
                print(f"rotorcrypt: {message}", file=sys.stderr)
            diagnostics = len(errors)

        def consume(data: bytes) -> None:
            emit(operation.feed(data if encrypt else data.decode("ascii")))
            report()

        if args.text is not None:
            consume(args.text.encode("ascii"))
        else:
            with open(args.input, "rb") if args.input else nullcontext(sys.stdin.buffer) as stream:
                timeout = args.idle_seconds if encrypt and args.mode == "checked" else None
                for data in _chunks(stream, timeout):
                    if data is None:
                        emit(operation.flush())
                    else:
                        consume(data)
        emit(operation.finish())
        report()
        return 1 if getattr(operation, "errors", []) else 0
    except BrokenPipeError:
        # Prevent Python's final stdout flush from printing a second traceback.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
        return 141
    except KeyboardInterrupt:
        print("rotorcrypt: interrupted; the current stream may be incomplete", file=sys.stderr)
        return 130
    except (OSError, ValueError) as error:
        print(f"rotorcrypt: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
