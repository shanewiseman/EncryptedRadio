"""Lossless case conventions remain authenticated and explicitly selected."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from encrypted_radio.config import load_machine
from encrypted_radio.seal import (
    HEADER, SealDecoder, SealEncoder, SealKey, SealStreamError, machine_digest, session_key,
)

ROOT = Path(__file__).resolve().parents[1]
# Deterministic, public fixtures; these are never used for private messages.
KEY = SealKey(bytes(range(32)))
SESSION = bytes(range(32, 64))
ENCODINGS = ("uppercase-first", "lowercase-first")


def frames(symbols: str) -> list[str]:
    return [part + ")" for part in symbols.split(")") if part]


def unpack(frame: str) -> bytes:
    body = frame[4:-1]
    return base64.b32decode(body + "=" * (-len(body) % 8))


def envelope(packet: bytes) -> str:
    return "VVV(" + base64.b32encode(packet).decode("ascii").rstrip("=") + ")"


class SealEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.machine = load_machine()

    def encode(self, data: bytes, *, mode="checked", encoding="lowercase-first", block_size=128) -> str:
        encoder = SealEncoder(self.machine, KEY, mode, block_size, text_encoding=encoding)
        return encoder.feed(data) + encoder.finish()

    def receive_state(self, decoder):
        return (decoder.session_id, decoder.expected_sequence, decoder.complete,
                decoder._aead, tuple(decoder._past_sessions))

    def test_all_ascii_incremental_roundtrip_in_both_modes(self):
        original = bytes(range(128)) * 2
        for mode in ("checked", "raw"):
            for block_size in (1, 17, 128, 256):
                with self.subTest(mode=mode, block_size=block_size):
                    encoder = SealEncoder(self.machine, KEY, mode, block_size, text_encoding="lowercase-first")
                    symbols = "".join(encoder.feed(original[i:i + 13]) for i in range(0, len(original), 13))
                    symbols += encoder.finish()
                    decoder = SealDecoder(self.machine, KEY, mode, text_encoding="lowercase-first")
                    result = b"".join(decoder.feed(char) for char in symbols) + decoder.finish()
                    self.assertEqual(result, original)
                    self.assertEqual(decoder.errors, [])
                    self.assertTrue(decoder.complete)

    def test_lowercase_first_is_default_and_preserves_positional_arguments(self):
        original = b"MiXeD + text\x00\n"
        for mode in ("checked", "raw"):
            with self.subTest(mode=mode), patch("encrypted_radio.seal.secrets.token_bytes", return_value=SESSION):
                default = SealEncoder(self.machine, KEY, mode, 8)
                self.assertEqual(default.text_encoding, "lowercase-first")
                symbols = default.feed(original) + default.finish()
                self.assertEqual(symbols, self.encode(original, mode=mode, encoding="lowercase-first", block_size=8))
                self.assertTrue(all(HEADER.unpack_from(unpack(frame))[2] & 4 for frame in frames(symbols)))
                decoder = SealDecoder(self.machine, KEY, mode)
                self.assertEqual(decoder.text_encoding, "lowercase-first")
                self.assertEqual(decoder.feed(symbols) + decoder.finish(), original)
                self.assertEqual(decoder.errors, [])

    def test_ascii_alias_is_equivalent_to_explicit_uppercase_first(self):
        original = bytes(range(128))
        for mode in ("checked", "raw"):
            with self.subTest(mode=mode), patch("encrypted_radio.seal.secrets.token_bytes", return_value=SESSION):
                encoder = SealEncoder(self.machine, KEY, mode, text_encoding="ascii")
                self.assertEqual(encoder.text_encoding, "uppercase-first")
                wire = encoder.feed(original) + encoder.finish()
                self.assertEqual(wire, self.encode(original, mode=mode, encoding="uppercase-first"))
                for selection in ("ascii", "uppercase-first"):
                    decoder = SealDecoder(self.machine, KEY, mode, text_encoding=selection)
                    self.assertEqual(decoder.text_encoding, "uppercase-first")
                    self.assertEqual(decoder.feed(wire) + decoder.finish(), original)
                    self.assertEqual(decoder.errors, [])

    def test_flags_bind_both_modes_and_end_records_without_changing_wire_length(self):
        original = b"This message is encrypted using wwii technology"
        digest = machine_digest(self.machine)
        for mode in ("checked", "raw"):
            lengths = []
            for encoding in ENCODINGS:
                with self.subTest(mode=mode, encoding=encoding):
                    wire = self.encode(original, mode=mode, encoding=encoding)
                    lengths.append(len(wire))
                    for index, frame in enumerate(frames(wire)):
                        packet = unpack(frame)
                        _, _, flag, session, sequence, plainlen, _ = HEADER.unpack_from(packet)
                        self.assertEqual(flag, 2 * (mode == "raw") + 4 * (encoding == "lowercase-first") + index)
                        self.assertEqual(sequence, index)
                        expected = original if index == 0 else b""
                        self.assertEqual(plainlen, len(expected))
                        aead = ChaCha20Poly1305(session_key(KEY, session, digest, mode))
                        plaintext = aead.decrypt(b"\0" * 8 + sequence.to_bytes(4, "big"),
                                                 packet[HEADER.size:], packet[:HEADER.size] + digest)
                        self.assertEqual(plaintext, expected.swapcase() if encoding == "lowercase-first" else expected)
            self.assertEqual(lengths, [297, 297])

    def test_empty_session_requires_matching_encoding(self):
        for mode in ("checked", "raw"):
            with self.subTest(mode=mode):
                wire = self.encode(b"", mode=mode)
                self.assertEqual(len(frames(wire)), 1)
                decoder = SealDecoder(self.machine, KEY, mode, text_encoding="lowercase-first")
                self.assertEqual(decoder.feed(wire) + decoder.finish(), b"")
                self.assertTrue(decoder.complete)
                self.assertEqual(decoder.errors, [])
                mismatch = SealDecoder(self.machine, KEY, mode, text_encoding="uppercase-first")
                if mode == "raw":
                    with self.assertRaisesRegex(SealStreamError, "text encoding does not match"):
                        mismatch.feed(wire)
                else:
                    self.assertEqual(mismatch.feed(wire), b"")
                    self.assertEqual(mismatch.errors, ["seal frame text encoding does not match the receiver"])
                self.assertIsNone(mismatch.session_id)
                self.assertFalse(mismatch.complete)

    def test_mismatched_encoding_releases_nothing_and_preserves_receive_state(self):
        for mode in ("checked", "raw"):
            for sender_encoding, receiver_encoding in (ENCODINGS, ENCODINGS[::-1]):
                with self.subTest(mode=mode, sender=sender_encoding):
                    decoder = SealDecoder(self.machine, KEY, mode, text_encoding=receiver_encoding)
                    state = self.receive_state(decoder)
                    wire = self.encode(b"MiXeD secret", mode=mode, encoding=sender_encoding)
                    if mode == "raw":
                        with self.assertRaisesRegex(SealStreamError, "text encoding does not match"):
                            decoder.feed(wire)
                    else:
                        self.assertEqual(decoder.feed(wire), b"")
                        self.assertTrue(all("text encoding does not match" in message for message in decoder.errors))
                    self.assertEqual(self.receive_state(decoder), state)

    def test_tampered_encoding_flag_cannot_bypass_authentication_or_change_state(self):
        for mode in ("checked", "raw"):
            for receiver_encoding in ENCODINGS:
                with self.subTest(mode=mode, receiver=receiver_encoding):
                    sender_encoding = "uppercase-first" if receiver_encoding == "lowercase-first" else "lowercase-first"
                    packet = bytearray(unpack(frames(self.encode(b"MiXeD secret", mode=mode,
                                                                encoding=sender_encoding))[0]))
                    packet[3] ^= 4
                    # Re-encode valid canonical Base32; the original AEAD tag must still fail.
                    decoder = SealDecoder(self.machine, KEY, mode, text_encoding=receiver_encoding)
                    state = self.receive_state(decoder)
                    if mode == "raw":
                        with self.assertRaisesRegex(SealStreamError, "authentication failed"):
                            decoder.feed(envelope(packet))
                    else:
                        self.assertEqual(decoder.feed(envelope(packet)), b"")
                        self.assertIn("authentication failed", decoder.errors[0])
                    self.assertEqual(self.receive_state(decoder), state)

    def test_rejected_encoding_does_not_replace_existing_session(self):
        first, second, end = frames(self.encode(b"AaBb", block_size=2))
        decoder = SealDecoder(self.machine, KEY, text_encoding="lowercase-first")
        self.assertEqual(decoder.feed(first), b"Aa")
        state = self.receive_state(decoder)
        foreign = self.encode(b"Foreign", encoding="uppercase-first")
        self.assertEqual(decoder.feed(foreign), b"")
        self.assertEqual(self.receive_state(decoder), state)
        packet = bytearray(unpack(second))
        packet[3] ^= 4
        self.assertEqual(decoder.feed(envelope(packet)), b"")
        self.assertEqual(self.receive_state(decoder), state)
        self.assertEqual(decoder.feed(second + end) + decoder.finish(), b"Bb")
        self.assertTrue(decoder.complete)
        self.assertTrue(decoder.errors)

    def test_ascii_validation_precedes_case_conversion_and_state_changes(self):
        encoder = SealEncoder(self.machine, KEY, text_encoding="lowercase-first")
        with self.assertRaisesRegex(ValueError, "ASCII"):
            encoder.feed(b"\xff")
        self.assertEqual(encoder.sequence, 0)
        self.assertEqual(encoder.buffer, b"")
        digest = machine_digest(self.machine)
        header = HEADER.pack(b"SC", 1, 4, SESSION, 0, 1, digest[:8])
        aead = ChaCha20Poly1305(session_key(KEY, SESSION, digest))
        packet = header + aead.encrypt(b"\0" * 12, b"\xff", header + digest)
        decoder = SealDecoder(self.machine, KEY, text_encoding="lowercase-first")
        state = self.receive_state(decoder)
        self.assertEqual(decoder.feed(envelope(packet)), b"")
        self.assertEqual(decoder.errors, ["authenticated seal plaintext is not ASCII"])
        self.assertEqual(self.receive_state(decoder), state)

    def test_invalid_encoding_and_unknown_flag_bits_fail(self):
        for constructor in (SealEncoder, SealDecoder):
            for encoding in ("", "uppercase", None, 4):
                with self.subTest(constructor=constructor, encoding=encoding), self.assertRaises(ValueError):
                    constructor(self.machine, KEY, text_encoding=encoding)
        first = frames(self.encode(b"test"))[0]
        for flag in (8, 12, 255):
            packet = bytearray(unpack(first))
            packet[3] = flag
            decoder = SealDecoder(self.machine, KEY, text_encoding="lowercase-first")
            self.assertEqual(decoder.feed(envelope(packet)), b"")
            self.assertEqual(decoder.errors, ["unsupported seal frame header"])
            self.assertIsNone(decoder.session_id)


class SealEncodingCLITests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        self.key_path = self.path / "key.json"
        self.key_path.write_text(json.dumps(KEY.to_dict()), encoding="ascii")

    def run_cli(self, operation, *arguments, data=None):
        command = [sys.executable, "-m", "encrypted_radio.seal_cli", operation,
                   "--machine", str(ROOT / "examples/machine.json"), "--key", str(self.key_path), *arguments]
        return subprocess.run(command, input=data, capture_output=True, timeout=10)

    def test_text_file_and_stdin_preserve_case_and_mismatch_fails(self):
        original = bytes(range(128))
        path = self.path / "input.dat"
        path.write_bytes(original)
        for mode in ("checked", "raw"):
            for arguments, data, expected in (([], original, original), (["--input", str(path)], None, original),
                                              (["--text", "MiXeD text +\n"], None, b"MiXeD text +\n")):
                with self.subTest(mode=mode, arguments=arguments):
                    flags = ("--mode", mode)
                    encrypted = self.run_cli("encrypt", *flags, *arguments, data=data)
                    self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
                    self.assertEqual(encrypted.stderr, b"")
                    self.assertTrue(all(HEADER.unpack_from(unpack(frame))[2] & 4
                                        for frame in frames(encrypted.stdout.decode("ascii"))))
                    actual = self.run_cli("decrypt", *flags, data=encrypted.stdout)
                    self.assertEqual(actual.returncode, 0, actual.stderr)
                    self.assertEqual(actual.stdout, expected)
                    self.assertEqual(actual.stderr, b"")
            mismatch = self.run_cli("decrypt", "--mode", mode, "--uppercase-first", data=encrypted.stdout)
            self.assertEqual(mismatch.returncode, 1, mismatch.stderr)
            self.assertEqual(mismatch.stdout, b"")
            self.assertIn(b"text encoding does not match", mismatch.stderr)

    def test_uppercase_shorthand_long_option_and_ascii_alias_interoperate(self):
        original = b"MiXeD text +\n"
        choices = (("--uppercase-first",), ("--text-encoding", "uppercase-first"), ("--text-encoding", "ascii"))
        for mode in ("checked", "raw"):
            for sender in choices:
                with self.subTest(mode=mode, sender=sender):
                    encrypted = self.run_cli("encrypt", "--mode", mode, *sender, data=original)
                    self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
                    self.assertTrue(all(not HEADER.unpack_from(unpack(frame))[2] & 4
                                        for frame in frames(encrypted.stdout.decode("ascii"))))
                    for receiver in choices:
                        actual = self.run_cli("decrypt", "--mode", mode, *receiver, data=encrypted.stdout)
                        self.assertEqual(actual.returncode, 0, actual.stderr)
                        self.assertEqual(actual.stdout, original)
                    mismatch = self.run_cli("decrypt", "--mode", mode, data=encrypted.stdout)
                    self.assertEqual(mismatch.returncode, 1, mismatch.stderr)
                    self.assertEqual(mismatch.stdout, b"")
                    self.assertIn(b"text encoding does not match", mismatch.stderr)

    def test_encoding_options_are_mutually_exclusive(self):
        for operation in ("encrypt", "decrypt"):
            result = self.run_cli(operation, "--uppercase-first", "--text-encoding", "lowercase-first", data=b"")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"not allowed with argument", result.stderr)

    def test_keygen_rejects_any_explicit_encoding_without_creating_file(self):
        path = self.path / "new-key.json"
        for options in (("--text-encoding", "lowercase-first"), ("--text-encoding", "uppercase-first"),
                        ("--text-encoding", "ascii"), ("--uppercase-first",)):
            with self.subTest(options=options):
                result = subprocess.run([sys.executable, "-m", "encrypted_radio.seal_cli", "keygen", "--key",
                                         str(path), *options], capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertIn(b"keygen accepts --key only", result.stderr)
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
