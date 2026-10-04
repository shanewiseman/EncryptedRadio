"""Authenticated, bounded ASCII records for the replaceable symbol transport.

ChaCha20-Poly1305 authenticates each record before any plaintext is released.
Session keys are derived with HKDF from a fresh 256-bit random session salt.
This protocol does not provide persistent replay protection or key exchange.
"""
from __future__ import annotations

import base64
import binascii
from collections import deque
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import secrets
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import Machine

HEADER = struct.Struct("!2sBB32sIH8s")
MAX_PLAINTEXT = 256
MAX_BODY = 516
MAX_SEQUENCE = 0xFFFFFFFF
DOMAIN = b"EncryptedRadio/sealcrypt/v1\0"
_BASE32 = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
_HEX = frozenset("0123456789abcdefABCDEF")


def _mode_byte(mode: str) -> int:
    if mode not in ("checked", "raw"):
        raise ValueError("seal mode must be checked or raw")
    return int(mode == "raw")


@dataclass(frozen=True)
class SealKey:
    """A 256-bit shared secret; repr deliberately excludes its value."""

    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.key, bytes) or len(self.key) != 32:
            raise ValueError("seal key must contain exactly 32 bytes")

    @classmethod
    def from_dict(cls, value: dict) -> SealKey:
        if not isinstance(value, dict) or set(value) != {"version", "algorithm", "key_hex"}:
            raise ValueError("seal key must contain exactly version, algorithm, and key_hex")
        if type(value["version"]) is not int or value["version"] != 1:
            raise ValueError("unsupported seal key version")
        if value["algorithm"] != "chacha20-poly1305":
            raise ValueError("unsupported seal key algorithm")
        material = value["key_hex"]
        if not isinstance(material, str) or len(material) != 64 or any(char not in _HEX for char in material):
            raise ValueError("seal key_hex must contain exactly 64 hexadecimal characters")
        return cls(bytes.fromhex(material))

    def to_dict(self) -> dict:
        return {"version": 1, "algorithm": "chacha20-poly1305", "key_hex": self.key.hex()}


def generate_key() -> SealKey:
    return SealKey(secrets.token_bytes(32))


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("seal key JSON contains duplicate fields")
        result[name] = value
    return result


def load_key(path: str | Path) -> SealKey:
    """Read a bounded key file without echoing its contents in diagnostics."""
    with Path(path).open("rb") as stream:
        data = stream.read(4097)
    if len(data) > 4096:
        raise ValueError("seal key configuration exceeds 4096 bytes")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("seal key configuration must be valid UTF-8 JSON with unique fields") from None
    return SealKey.from_dict(value)


def machine_digest(machine: Machine) -> bytes:
    canonical = json.dumps(machine.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).digest()


def session_key(key: SealKey, session_id: bytes, machine_hash: bytes, mode: str = "checked") -> bytes:
    """Derive one mode- and public-configuration-bound session key."""
    if not isinstance(session_id, bytes) or len(session_id) != 32:
        raise ValueError("seal session ID must contain exactly 32 bytes")
    if not isinstance(machine_hash, bytes) or len(machine_hash) != 32:
        raise ValueError("seal machine digest must contain exactly 32 bytes")
    info = DOMAIN + bytes([_mode_byte(mode)]) + machine_hash
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=session_id, info=info).derive(key.key)


class SealStreamError(ValueError):
    """An integrity or ordering failure that terminates a raw seal stream."""


class SealEncoder:
    def __init__(self, machine: Machine, key: SealKey, mode: str = "checked", block_size: int = 128):
        self._mode = _mode_byte(mode)
        if type(block_size) is not int or not 1 <= block_size <= MAX_PLAINTEXT:
            raise ValueError("block size must be an integer from 1 to 256")
        self.machine, self.key, self.mode, self.block_size = machine, key, mode, block_size
        self.machine_hash = machine_digest(machine)
        # Session IDs cannot be supplied by callers: a fresh salt prevents a
        # repeated per-record nonce from repeating under the same session key.
        self.session_id = secrets.token_bytes(32)
        self._aead = ChaCha20Poly1305(session_key(key, self.session_id, self.machine_hash, mode))
        self.sequence = 0
        self.buffer = bytearray()
        self.closed = False

    def _frame(self, data: bytes, end: bool = False) -> str:
        if self.sequence > MAX_SEQUENCE or (not end and self.sequence == MAX_SEQUENCE):
            raise ValueError("seal session sequence exhausted")
        flag = self._mode * 2 + int(end)
        header = HEADER.pack(b"SC", 1, flag, self.session_id, self.sequence, len(data), self.machine_hash[:8])
        nonce = b"\0" * 8 + struct.pack("!I", self.sequence)
        packet = header + self._aead.encrypt(nonce, data, header + self.machine_hash)
        body = base64.b32encode(packet).decode("ascii").rstrip("=")
        self.sequence += 1
        return "VVV(" + body + ")"

    def feed(self, data: bytes) -> str:
        if self.closed:
            raise ValueError("seal encoder is already finished")
        if not isinstance(data, (bytes, bytearray)) or any(byte > 127 for byte in data):
            raise ValueError("input must contain ASCII bytes only")
        result = []
        view = memoryview(data)
        while view:
            take = min(self.block_size - len(self.buffer), len(view))
            self.buffer.extend(view[:take])
            view = view[take:]
            if len(self.buffer) == self.block_size:
                result.append(self.flush())
        if self.mode == "raw":
            result.append(self.flush())
        return "".join(result)

    def flush(self) -> str:
        if self.closed:
            raise ValueError("seal encoder is already finished")
        if not self.buffer:
            return ""
        output = self._frame(bytes(self.buffer))
        self.buffer.clear()
        return output

    def finish(self) -> str:
        if self.closed:
            raise ValueError("seal encoder is already finished")
        output = self.flush() + self._frame(b"", end=True)
        self.closed = True
        return output


class SealDecoder:
    def __init__(self, machine: Machine, key: SealKey, mode: str = "checked"):
        self._mode = _mode_byte(mode)
        self.machine, self.key, self.mode = machine, key, mode
        self.machine_hash = machine_digest(machine)
        self.errors: list[str] = []
        self.error_count = 0
        self.complete = False
        self.session_id: bytes | None = None
        self.expected_sequence = 0
        self.body: list[str] | None = None
        self.closed = False
        self._failed = False
        self._preamble = 0
        self._outside_noise = False
        self._past_sessions: deque[bytes] = deque(maxlen=64)
        self._aead: ChaCha20Poly1305 | None = None

    def _error(self, message: str) -> None:
        self.error_count += 1
        if len(self.errors) < 128:
            self.errors.append(message)
        elif len(self.errors) == 128:
            self.errors.append("additional errors omitted after 128 diagnostics")
        if self.mode == "raw":
            self._failed = True
            self.complete = False
            raise SealStreamError(message)

    def _ensure_open(self) -> None:
        if self._failed:
            raise SealStreamError("seal decoder stopped after a raw stream error")
        if self.closed:
            raise ValueError("seal decoder is already finished")

    def _packet(self, body: str) -> bytes:
        try:
            packet = base64.b32decode(body + "=" * (-len(body) % 8))
        except (binascii.Error, ValueError):
            raise ValueError("invalid Base32 seal frame") from None
        if len(packet) < HEADER.size + 16:
            raise ValueError("seal frame is shorter than its header and authentication tag")
        if base64.b32encode(packet).decode("ascii").rstrip("=") != body:
            raise ValueError("noncanonical Base32 seal frame")
        magic, version, flag, session, sequence, plainlen, fingerprint = HEADER.unpack_from(packet)
        if magic != b"SC" or version != 1 or flag not in (0, 1, 2, 3):
            raise ValueError("unsupported seal frame header")
        if flag // 2 != self._mode:
            raise ValueError("seal frame mode does not match the receiver")
        end = bool(flag & 1)
        if (end and plainlen != 0) or (not end and not 1 <= plainlen <= MAX_PLAINTEXT):
            raise ValueError("invalid seal plaintext length")
        if not end and sequence == MAX_SEQUENCE:
            raise ValueError("the final seal sequence is reserved for an end frame")
        if len(packet) != HEADER.size + plainlen + 16:
            raise ValueError("invalid seal ciphertext length")
        if fingerprint != self.machine_hash[:8]:
            raise ValueError("public machine configuration does not match")
        aead = self._aead if session == self.session_id else None
        if aead is None:
            aead = ChaCha20Poly1305(session_key(self.key, session, self.machine_hash, self.mode))
        nonce = b"\0" * 8 + struct.pack("!I", sequence)
        try:
            plaintext = aead.decrypt(nonce, packet[HEADER.size:], packet[:HEADER.size] + self.machine_hash)
        except InvalidTag:
            raise ValueError("seal authentication failed (damaged data, incorrect key, or context)") from None
        if any(byte > 127 for byte in plaintext):
            raise ValueError("authenticated seal plaintext is not ASCII")
        # Unauthenticated packets never change session or sequence state.
        if session != self.session_id:
            if session in self._past_sessions:
                self._error("ignored frame from a completed or superseded seal session")
                return b""
            if self.session_id is not None:
                if not self.complete:
                    self._error("previous seal session ended without an end frame")
                self._past_sessions.append(self.session_id)
            self.session_id = session
            self._aead = aead
            self.expected_sequence = 0
            self.complete = False
        if sequence < self.expected_sequence:
            self._error(f"ignored duplicate or old seal frame {sequence}")
            return b""
        if self.complete:
            raise ValueError("received a seal frame after the session end")
        if sequence > self.expected_sequence:
            self._error(f"missing seal frames {self.expected_sequence} through {sequence - 1}")
        self.expected_sequence = sequence + 1
        self.complete = end
        return plaintext

    def feed(self, symbols: str) -> bytes:
        self._ensure_open()
        if not isinstance(symbols, str):
            raise ValueError("seal decoder input must be an ASCII symbol string")
        output = bytearray()
        for char in symbols:
            if char == "(":
                if self.body is not None:
                    self._error("partial seal frame replaced by a new opening delimiter")
                self.body = []
                self._preamble = 0
                self._outside_noise = False
            elif self.body is not None:
                if char == ")":
                    body, self.body = "".join(self.body), None
                    try:
                        output.extend(self._packet(body))
                    except SealStreamError:
                        raise
                    except ValueError as error:
                        self._error(str(error))
                elif char not in _BASE32:
                    self._error("seal frame contains an invalid symbol or reception error marker")
                    self.body = None
                elif len(self.body) == MAX_BODY:
                    self._error("seal frame exceeds the maximum encoded length")
                    self.body = None
                else:
                    self.body.append(char)
            elif char == "V":
                if self._preamble == 3:
                    if not self._outside_noise:
                        self._error("unexpected symbols outside a seal frame")
                        self._outside_noise = True
                else:
                    self._preamble += 1
            else:
                if not self._outside_noise:
                    self._error("unexpected symbols outside a seal frame")
                    self._outside_noise = True
                self._preamble = 0
        return bytes(output)

    def finish(self) -> bytes:
        self._ensure_open()
        self.closed = True
        if self.body is not None:
            self.complete = False
            self._error("truncated seal frame at end of input")
            self.body = None
        if self._preamble:
            self.complete = False
            self._error("truncated seal frame preamble at end of input")
        if not self.complete:
            self._error("missing seal session end frame")
        return b""
