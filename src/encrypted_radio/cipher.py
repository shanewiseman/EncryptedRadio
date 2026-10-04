"""Shared batch and incremental cipher APIs used by CLI and demos."""
from dataclasses import dataclass

from .codec import ASCIIDecoder, encode_ascii
from .config import Key, Machine
from .framing import CheckedDecoder, CheckedEncoder
from .rotor import RotorMachine


class RawEncoder:
    def __init__(self, machine: Machine, key: Key):
        self.rotor = RotorMachine(machine, key)
        self.closed = False

    def feed(self, data: bytes) -> str:
        if self.closed:
            raise ValueError("raw encoder is already finished")
        return self.rotor.transform(encode_ascii(data))

    def finish(self) -> str:
        self.closed = True
        return ""


class RawDecoder:
    def __init__(self, machine: Machine, key: Key):
        self.rotor = RotorMachine(machine, key)
        self.codec = ASCIIDecoder()
        self.closed = False

    def feed(self, text: str) -> bytes:
        if self.closed:
            raise ValueError("raw decoder is already finished")
        return self.codec.feed(self.rotor.transform(text))

    def finish(self) -> bytes:
        self.closed = True
        return self.codec.finish()


@dataclass
class DecodeResult:
    plaintext: bytes
    errors: list[str]
    complete: bool


def encrypt_bytes(data: bytes, machine: Machine, key: Key, mode: str = "checked", block_size: int = 128, session_id: bytes | None = None) -> str:
    if mode not in ("raw", "checked"):
        raise ValueError("cipher mode must be raw or checked")
    encoder = RawEncoder(machine, key) if mode == "raw" else CheckedEncoder(machine, key, block_size, session_id)
    return encoder.feed(data) + encoder.finish()


def decrypt_text(text: str, machine: Machine, key: Key, mode: str = "checked") -> DecodeResult:
    if mode not in ("raw", "checked"):
        raise ValueError("cipher mode must be raw or checked")
    decoder = RawDecoder(machine, key) if mode == "raw" else CheckedDecoder(machine, key)
    try:
        plaintext = decoder.feed(text)
        plaintext += decoder.finish()
    except ValueError as error:
        return DecodeResult(b"", [str(error)], False)
    return DecodeResult(plaintext, list(getattr(decoder, "errors", [])), getattr(decoder, "complete", True))
