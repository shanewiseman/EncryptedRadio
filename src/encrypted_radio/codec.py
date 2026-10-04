"""Losslessly encode every ASCII byte using the Morse-compatible alphabet."""
from .config import ALPHABET

_DIRECT = frozenset(ALPHABET) - {"+"}
_HEX = frozenset("0123456789ABCDEF")
DEFAULT_TEXT_ENCODING = "lowercase-first"
TEXT_ENCODINGS = ("lowercase-first", "uppercase-first", "ascii")


def validate_text_encoding(text_encoding: str) -> None:
    if text_encoding not in TEXT_ENCODINGS:
        raise ValueError("text encoding must be lowercase-first or uppercase-first (ascii is a legacy alias)")


def normalize_text_encoding(text_encoding: str) -> str:
    validate_text_encoding(text_encoding)
    return "uppercase-first" if text_encoding == "ascii" else text_encoding


def encode_ascii(data: bytes, *, text_encoding: str = DEFAULT_TEXT_ENCODING) -> str:
    text_encoding = normalize_text_encoding(text_encoding)
    if any(byte > 127 for byte in data):
        raise ValueError("input must contain ASCII bytes only")
    if text_encoding == "lowercase-first":
        data = data.swapcase()
    return "".join(chr(byte) if chr(byte) in _DIRECT else f"+{byte:02X}" for byte in data)


class ASCIIDecoder:
    def __init__(self, *, text_encoding: str = DEFAULT_TEXT_ENCODING) -> None:
        self.text_encoding = normalize_text_encoding(text_encoding)
        self.pending = ""

    def feed(self, symbols: str) -> bytes:
        result = bytearray()
        for char in symbols:
            if self.pending:
                if char not in _HEX:
                    raise ValueError("malformed ASCII escape: expected uppercase hexadecimal")
                self.pending += char
                if len(self.pending) == 3:
                    value = int(self.pending[1:], 16)
                    if value > 127:
                        raise ValueError("ASCII escape is outside the ASCII range")
                    result.append(value)
                    self.pending = ""
            elif char == "+":
                self.pending = char
            elif char in _DIRECT:
                result.append(ord(char))
            else:
                raise ValueError("decoded symbol is outside the transport alphabet")
        plaintext = bytes(result)
        return plaintext.swapcase() if self.text_encoding == "lowercase-first" else plaintext

    def finish(self) -> bytes:
        if self.pending:
            raise ValueError("truncated ASCII escape")
        return b""


def decode_ascii(symbols: str, *, text_encoding: str = DEFAULT_TEXT_ENCODING) -> bytes:
    decoder = ASCIIDecoder(text_encoding=text_encoding)
    result = decoder.feed(symbols)
    decoder.finish()
    return result
