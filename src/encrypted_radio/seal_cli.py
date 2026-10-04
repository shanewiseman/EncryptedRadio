"""Authenticated ASCII encryption with rotorcrypt-compatible streaming options."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys

from .config import load_machine
from .seal import SealDecoder, SealEncoder, SealStreamError, generate_key, load_key
from .streams import iter_chunks


def _parser():
    parser = argparse.ArgumentParser(
        prog="sealcrypt",
        description="ChaCha20-Poly1305 authenticated ASCII encryption for text and Morse pipelines.",
        epilog="Requires a sealcrypt key at both ends. Raw mode emits immediate authenticated records; "
               "decryption waits for a complete record and never releases unauthenticated plaintext.",
    )
    parser.add_argument("operation", choices=("encrypt", "decrypt", "keygen"),
                        help="keygen creates a random 256-bit key with mode 0600 and refuses overwrite")
    parser.add_argument("--machine", help="required for encrypt/decrypt: public machine JSON authenticated as context")
    parser.add_argument("--key", required=True, type=Path, help="private sealcrypt key JSON; keygen creates this path")
    parser.add_argument("--mode", choices=("checked", "raw"), default="checked")
    parser.add_argument("--block-size", type=int, default=128, help="plaintext bytes per record, 1–256 (default: 128)")
    parser.add_argument("--idle-seconds", type=float, default=5.0, help="checked encryption idle flush interval (default: 5)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="complete ASCII input")
    source.add_argument("--input", help="input filename; default is streaming stdin")
    return parser


def _private_parents(path: Path):
    """Apply 0700 to every directory we create, without changing existing parents."""
    if path.is_dir():
        return
    if path.parent != path:
        _private_parents(path.parent)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if not path.is_dir():
            raise


def _write_key(path: Path):
    _private_parents(path.parent)
    # O_EXCL refuses both existing files and symlinks, including dangling symlinks.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            json.dump(generate_key().to_dict(), output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if args.operation != "keygen" and not args.machine:
        parser.error("--machine is required for encrypt and decrypt")
    if args.operation == "keygen" and (args.machine is not None or args.text is not None or args.input is not None
                                       or args.mode != "checked" or args.block_size != 128 or args.idle_seconds != 5):
        parser.error("keygen accepts --key only")
    try:
        if args.operation == "keygen":
            _write_key(args.key)
            print(f"sealcrypt: created private key at {args.key}", file=sys.stderr)
            return 0
        if not 0 < args.idle_seconds <= 3600:
            raise ValueError("idle seconds must be greater than zero and at most 3600")
        if not 1 <= args.block_size <= 256:
            raise ValueError("block size must be between 1 and 256")
        machine, key = load_machine(args.machine), load_key(args.key)
        encrypt = args.operation == "encrypt"
        operation = (SealEncoder(machine, key, mode=args.mode, block_size=args.block_size)
                     if encrypt else SealDecoder(machine, key, mode=args.mode))
        reported = 0

        def emit(value):
            if value:
                sys.stdout.buffer.write(value.encode("ascii") if isinstance(value, str) else value)
                sys.stdout.buffer.flush()

        def report():
            nonlocal reported
            errors = getattr(operation, "errors", [])
            for message in errors[reported:]:
                print(f"sealcrypt: {message}", file=sys.stderr)
            reported = len(errors)

        def consume(data):
            emit(operation.feed(data if encrypt else data.decode("ascii")))
            report()

        if args.text is not None:
            consume(args.text.encode("ascii"))
        else:
            with open(args.input, "rb") if args.input else nullcontext(sys.stdin.buffer) as source:
                timeout = args.idle_seconds if encrypt and args.mode == "checked" else None
                for chunk in iter_chunks(source, timeout):
                    if chunk is None:
                        emit(operation.flush())
                    else:
                        consume(chunk)
        emit(operation.finish())
        report()
        return 1 if getattr(operation, "errors", []) else 0
    except BrokenPipeError:
        descriptor = os.open(os.devnull, os.O_WRONLY)
        os.dup2(descriptor, sys.stdout.fileno())
        os.close(descriptor)
        return 141
    except KeyboardInterrupt:
        print("sealcrypt: interrupted; the stream may be incomplete", file=sys.stderr)
        return 130
    except SealStreamError as error:
        print(f"sealcrypt: {error}", file=sys.stderr)
        return 1
    except RecursionError:
        print("sealcrypt: configuration JSON is nested too deeply", file=sys.stderr)
        return 2
    except (ValueError, OSError) as error:
        print(f"sealcrypt: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
