"""Losslessly encode every ASCII byte using the Morse-compatible alphabet."""
from .config import ALPHABET

_DIRECT = frozenset(ALPHABET) - {"+"}
_HEX = frozenset("0123456789ABCDEF")


def encode_ascii(data: bytes) -> str:
    if any(byte > 127 for byte in data):
        raise ValueError("input must contain ASCII bytes only")
    return "".join(chr(byte) if chr(byte) in _DIRECT else f"+{byte:02X}" for byte in data)


class ASCIIDecoder:
    def __init__(self) -> None:
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
        return bytes(result)

    def finish(self) -> bytes:
        if self.pending:
            raise ValueError("truncated ASCII escape")
        return b""


def decode_ascii(symbols: str) -> bytes:
    decoder = ASCIIDecoder()
    result = decoder.feed(symbols)
    decoder.finish()
    return result
