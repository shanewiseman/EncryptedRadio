"""Bounded, recoverable checked blocks over an ASCII symbol transport.

CRC32 detects accidental damage only; this format is not authenticated.
"""
from __future__ import annotations

import base64
import binascii
from collections import deque
import hashlib
import secrets
import struct
import zlib

from .codec import decode_ascii, encode_ascii
from .config import Key, Machine
from .rotor import RotorMachine

HEADER = struct.Struct("!2sBB8sIHH8sI")
CRC = struct.Struct("!I")
MAX_BODY = 1287
MAX_CIPHERTEXT = 768
MAX_SEQUENCE = 0xFFFFFFFF
DOMAIN = b"EncryptedRadio/checked-v1/start\0"
_BASE32 = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def block_positions(key: Key, session: bytes, sequence: int) -> tuple[int, ...]:
    digest = hashlib.sha256(DOMAIN + session + struct.pack("!I", sequence)).digest()
    value = int.from_bytes(digest, "big")
    positions = []
    for initial in key.positions:
        value, offset = divmod(value, 49)
        positions.append((initial + offset) % 49)
    return tuple(positions)


class CheckedEncoder:
    def __init__(self, machine: Machine, key: Key, block_size: int = 128, session_id: bytes | None = None):
        if type(block_size) is not int or not 1 <= block_size <= 256:
            raise ValueError("block size must be an integer from 1 to 256")
        self.machine, self.key, self.block_size = machine, key, block_size
        self.session_id = secrets.token_bytes(8) if session_id is None else session_id
        if not isinstance(self.session_id, bytes) or len(self.session_id) != 8:
            raise ValueError("session ID must contain exactly eight bytes")
        self.sequence = 0
        self.buffer = bytearray()
        self.closed = False

    def _frame(self, data: bytes, end: bool = False) -> str:
        # Reserve the final sequence for the end marker rather than wrapping.
        if self.sequence > MAX_SEQUENCE or (not end and self.sequence == MAX_SEQUENCE):
            raise ValueError("checked session sequence exhausted")
        encrypted = RotorMachine(self.machine, self.key, block_positions(self.key, self.session_id, self.sequence)).transform(encode_ascii(data)).encode("ascii")
        header = HEADER.pack(b"ER", 1, int(end), self.session_id, self.sequence,
                             len(data), len(encrypted), self.machine.fingerprint, zlib.crc32(data))
        packet = header + encrypted
        body = base64.b32encode(packet + CRC.pack(zlib.crc32(packet))).decode("ascii").rstrip("=")
        self.sequence += 1
        return "VVV(" + body + ")"

    def feed(self, data: bytes) -> str:
        if self.closed:
            raise ValueError("checked encoder is already finished")
        if any(byte > 127 for byte in data):
            raise ValueError("input must contain ASCII bytes only")
        result = []
        # The retained buffer never exceeds one plaintext block.
        view = memoryview(data)
        while view:
            take = min(self.block_size - len(self.buffer), len(view))
            self.buffer.extend(view[:take])
            view = view[take:]
            if len(self.buffer) == self.block_size:
                result.append(self.flush())
        return "".join(result)

    def flush(self) -> str:
        if self.closed:
            raise ValueError("checked encoder is already finished")
        if not self.buffer:
            return ""
        frame = self._frame(bytes(self.buffer))
        self.buffer.clear()
        return frame

    def finish(self) -> str:
        if self.closed:
            raise ValueError("checked encoder is already finished")
        output = self.flush() + self._frame(b"", end=True)
        self.closed = True
        return output


class CheckedDecoder:
    def __init__(self, machine: Machine, key: Key):
        self.machine, self.key = machine, key
        self.errors: list[str] = []
        self.error_count = 0
        self.complete = False
        self.session_id: bytes | None = None
        self.expected_sequence = 0
        self.body: list[str] | None = None
        self.closed = False
        self._preamble = 0
        self._outside_noise = False
        self._past_sessions: deque[bytes] = deque(maxlen=64)

    def _error(self, message: str) -> None:
        self.error_count += 1
        # Keep long-running reception bounded even when the input is hostile/noisy.
        if len(self.errors) < 128:
            self.errors.append(message)
        elif len(self.errors) == 128:
            self.errors.append("additional errors omitted after 128 diagnostics")

    def _packet(self, body: str) -> bytes:
        try:
            packet = base64.b32decode(body + "=" * (-len(body) % 8))
        except (binascii.Error, ValueError):
            raise ValueError("invalid Base32 frame") from None
        if len(packet) < HEADER.size + CRC.size:
            raise ValueError("frame is shorter than its header")
        # Reject noncanonical pad bits as well as invalid alphabet/padding.
        if base64.b32encode(packet).decode("ascii").rstrip("=") != body:
            raise ValueError("noncanonical Base32 frame")
        if zlib.crc32(packet[:-4]) != CRC.unpack(packet[-4:])[0]:
            raise ValueError("frame envelope checksum mismatch")
        magic, version, flag, session, sequence, plainlen, cipherlen, fingerprint, plaincrc = HEADER.unpack_from(packet)
        if magic != b"ER" or version != 1 or flag not in (0, 1):
            raise ValueError("unsupported checked frame header")
        if cipherlen > MAX_CIPHERTEXT or len(packet) != HEADER.size + cipherlen + CRC.size:
            raise ValueError("invalid ciphertext length")
        if flag == 1:
            if plainlen or cipherlen or plaincrc:
                raise ValueError("end frame must have an empty payload")
        elif not 1 <= plainlen <= 256 or not plainlen <= cipherlen <= 3 * plainlen:
            raise ValueError("invalid plaintext/ciphertext lengths")
        if fingerprint != self.machine.fingerprint:
            raise ValueError("public machine configuration does not match")
        try:
            ciphertext = packet[HEADER.size:-4].decode("ascii")
        except UnicodeError:
            raise ValueError("ciphertext is not ASCII") from None
        rotor = RotorMachine(self.machine, self.key, block_positions(self.key, session, sequence))
        plaintext = decode_ascii(rotor.transform(ciphertext))
        if len(plaintext) != plainlen or zlib.crc32(plaintext) != plaincrc:
            raise ValueError("plaintext checksum mismatch (damaged data or incorrect key)")
        # Only verified frames affect sequencing or release plaintext.
        if session != self.session_id:
            if session in self._past_sessions:
                self._error("ignored frame from a completed or superseded session")
                return b""
            if self.session_id is not None:
                if not self.complete:
                    self._error("previous session ended without an end frame")
                self._past_sessions.append(self.session_id)
            self.session_id = session
            self.expected_sequence = 0
            self.complete = False
        if sequence < self.expected_sequence:
            self._error(f"ignored duplicate or old frame {sequence}")
            return b""
        if self.complete:
            raise ValueError("received a frame after the session end")
        if sequence > self.expected_sequence:
            self._error(f"missing frames {self.expected_sequence} through {sequence - 1}")
        self.expected_sequence = sequence + 1
        self.complete = flag == 1
        return plaintext

    def feed(self, symbols: str) -> bytes:
        if self.closed:
            raise ValueError("checked decoder is already finished")
        output = bytearray()
        for char in symbols:
            if char == "(":
                if self.body is not None:
                    self._error("partial frame replaced by a new opening delimiter")
                self.body = []
                self._preamble = 0
                self._outside_noise = False
            elif self.body is not None:
                if char == ")":
                    body, self.body = "".join(self.body), None
                    try:
                        output.extend(self._packet(body))
                    except ValueError as error:
                        self._error(str(error))
                elif char not in _BASE32:
                    self._error("frame contains an invalid symbol or reception error marker")
                    self.body = None
                elif len(self.body) == MAX_BODY:
                    self._error("frame exceeds the maximum encoded length")
                    self.body = None
                else:
                    self.body.append(char)
            elif char == "V":
                if self._preamble == 3:
                    if not self._outside_noise:
                        self._error("unexpected symbols outside a checked frame")
                        self._outside_noise = True
                else:
                    self._preamble += 1
            else:
                if not self._outside_noise:
                    self._error("unexpected symbols outside a checked frame")
                    self._outside_noise = True
                self._preamble = 0
        return bytes(output)

    def finish(self) -> bytes:
        if self.closed:
            raise ValueError("checked decoder is already finished")
        self.closed = True
        if self.body is not None:
            self._error("truncated frame at end of input")
            self.complete = False
            self.body = None
        if self._preamble:
            self._error("truncated frame preamble at end of input")
            self.complete = False
        if not self.complete:
            self._error("missing session end frame")
        return b""
