"""Authenticated transport vectors, damage recovery and actual pipe acceptance."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import select
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from encrypted_radio.config import ALPHABET, Machine, load_machine
from encrypted_radio.seal import (
    MAX_BODY, MAX_SEQUENCE, SealDecoder, SealEncoder, SealKey, SealStreamError,
    generate_key, load_key,
)

ROOT = Path(__file__).resolve().parents[1]
# Public deterministic fixtures, never keys for real messages.
KEY_DATA = {"version": 1, "algorithm": "chacha20-poly1305", "key_hex": bytes(range(32)).hex()}
SESSION = bytes(range(32, 64))
WIRE_HEADER = struct.Struct("!2sBB32sIH8s")
DATA_VECTORS = {
    "checked": "VVV(KNBQCABAEERCGJBFEYTSQKJKFMWC2LRPGAYTEMZUGU3DOOBZHI5TYPJ6H4AAAAAAAAHGER77YGMFUY3NFT7WVNC5FLLQQTVZH2RRHUL5E5E2TAZZHINSF6ZHRCMM4ZPJ)",
    "raw": "VVV(KNBQCARAEERCGJBFEYTSQKJKFMWC2LRPGAYTEMZUGU3DOOBZHI5TYPJ6H4AAAAAAAAHGER77YGMFUY3NEPBMTZ5HDOLRH3G3FOVUGTUF7OY43OIKUK2YYNOIAX3XJ6HU)",
}


def frames(symbols: str) -> list[str]:
    return [part + ")" for part in symbols.split(")") if part]


def unpack(frame: str) -> bytes:
    body = frame[4:-1]
    return base64.b32decode(body + "=" * (-len(body) % 8))


def envelope(packet: bytes) -> str:
    return "VVV(" + base64.b32encode(packet).decode("ascii").rstrip("=") + ")"


def alter(frame: str, offset: int) -> str:
    packet = bytearray(unpack(frame))
    packet[offset] ^= 1
    return envelope(packet)


def reference_frame(machine: Machine, plaintext: bytes, *, sequence=0, mode="checked", end=False) -> str:
    """Independent RFC 5869 extract/expand and RFC 8439 AEAD composition.

    This does not call implementation serialization, KDF, nonce, or framing code.
    It intentionally supports unusual plaintext/flag combinations for negative tests.
    """
    canonical = json.dumps(machine.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    digest = hashlib.sha256(canonical).digest()
    prk = hmac.new(SESSION, bytes(range(32)), hashlib.sha256).digest()
    info = b"EncryptedRadio/sealcrypt/v1\0" + bytes([mode == "raw"]) + digest
    key = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
    flag = 2 * (mode == "raw") + end
    header = WIRE_HEADER.pack(b"SC", 1, flag, SESSION, sequence, len(plaintext), digest[:8])
    nonce = b"\x00" * 8 + sequence.to_bytes(4, "big")
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, plaintext, header + digest)
    return envelope(header + ciphertext)


class SealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.machine = load_machine()
        cls.key = SealKey.from_dict(KEY_DATA)

    def encode(self, data: bytes, mode="checked", block_size=128) -> str:
        encoder = SealEncoder(self.machine, self.key, mode=mode, block_size=block_size)
        return encoder.feed(data) + encoder.finish()

    def decode(self, symbols: str, *, key=None, machine=None, mode="checked"):
        decoder = SealDecoder(machine or self.machine, key or self.key, mode=mode)
        plaintext = decoder.feed(symbols) + decoder.finish()
        return plaintext, decoder

    def test_independent_wire_and_key_derivation_vector(self):
        # Affine permutations make the public fixture independent of bundled data.
        machine = Machine.from_dict({"version": 1, "alphabet": ALPHABET, "rotors": {
            name: {"wiring": "".join(ALPHABET[(a * i + b) % 49] for i in range(49)), "notches": [1, 48]}
            for name, a, b in (("A", 2, 1), ("B", 3, 2), ("C", 5, 3))}, "reflector": ALPHABET[::-1]})
        for mode in ("checked", "raw"):
            with self.subTest(mode=mode), patch("encrypted_radio.seal.secrets.token_bytes", return_value=SESSION):
                encoder = SealEncoder(machine, self.key, mode=mode)
                actual = encoder.feed(b"lowercase + \x00\n") + encoder.finish()
                expected = (reference_frame(machine, b"lowercase + \x00\n", mode=mode)
                            + reference_frame(machine, b"", sequence=1, mode=mode, end=True))
                self.assertEqual(frames(expected)[0], DATA_VECTORS[mode])
                self.assertEqual(actual, expected)
                decoder = SealDecoder(machine, self.key, mode=mode)
                self.assertEqual(decoder.feed(expected) + decoder.finish(), b"lowercase + \x00\n")
                self.assertTrue(decoder.complete)
                self.assertEqual(decoder.errors, [])

    def test_key_schema_and_redacted_representation(self):
        self.assertEqual(self.key.to_dict(), KEY_DATA)
        self.assertNotIn(KEY_DATA["key_hex"], repr(self.key))
        self.assertNotIn(repr(bytes(range(32))), repr(self.key))
        for field, value in (("version", True), ("version", 2), ("algorithm", "AES"),
                             ("key_hex", "00" * 31), ("key_hex", "00" * 33),
                             ("key_hex", "gg" * 32), ("key_hex", "  " * 32), ("key_hex", None)):
            invalid = dict(KEY_DATA)
            invalid[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                SealKey.from_dict(invalid)
        for invalid in ({}, [], {**KEY_DATA, "unknown": 1}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                SealKey.from_dict(invalid)
        generated = generate_key()
        self.assertEqual(len(bytes.fromhex(generated.to_dict()["key_hex"])), 32)
        self.assertNotEqual(generated.to_dict(), generate_key().to_dict())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.json"
            path.write_text(json.dumps(KEY_DATA), encoding="utf-8")
            self.assertEqual(load_key(path).to_dict(), KEY_DATA)
            path.write_bytes(b" " * 1_048_577)
            with self.assertRaises(ValueError):
                load_key(path)
            for malformed in (b"[" * 1500 + b"]" * 1500, b"\xff", b'{"version":1,"version":1}', b"{"):
                path.write_bytes(malformed)
                with self.subTest(malformed=malformed[:30]), self.assertRaises(ValueError):
                    load_key(path)

    def test_all_ascii_all_chunk_boundaries_and_modes(self):
        original = bytes(range(128)) * 3
        for mode in ("checked", "raw"):
            for block_size in (1, 17, 128, 256):
                with self.subTest(mode=mode, block_size=block_size):
                    encoder = SealEncoder(self.machine, self.key, mode=mode, block_size=block_size)
                    symbols = "".join(encoder.feed(original[i:i + 13]) for i in range(0, len(original), 13)) + encoder.finish()
                    self.assertLessEqual(set(symbols), set(ALPHABET))
                    decoder = SealDecoder(self.machine, self.key, mode=mode)
                    decoded = b"".join(decoder.feed(symbols[i:i + 7]) for i in range(0, len(symbols), 7)) + decoder.finish()
                    self.assertEqual(decoded, original)
                    self.assertEqual(decoder.errors, [])
                    self.assertTrue(decoder.complete)

    def test_explicit_flush_and_no_plaintext_before_authentication(self):
        encoder = SealEncoder(self.machine, self.key)
        self.assertEqual(encoder.feed(b"short"), "")
        first = encoder.flush()
        self.assertEqual(encoder.flush(), "")
        decoder = SealDecoder(self.machine, self.key)
        self.assertEqual(decoder.feed(first[:-1]), b"")
        self.assertEqual(decoder.feed(first[-1]), b"short")
        self.assertFalse(decoder.complete)
        self.assertEqual(decoder.feed(encoder.finish()) + decoder.finish(), b"")
        self.assertTrue(decoder.complete)
        self.assertEqual(decoder.errors, [])
        raw = SealEncoder(self.machine, self.key, mode="raw")
        self.assertTrue(raw.feed(b"a"))
        self.assertEqual(raw.feed(b""), "")

    def test_every_header_field_ciphertext_and_tag_are_protected(self):
        first, end = frames(self.encode(b"private"))
        # magic, version, flags, session, sequence, length, fingerprint, body, tag.
        for offset in (0, 2, 3, 4, 36, 40, 42, 50, len(unpack(first)) - 1):
            with self.subTest(offset=offset):
                plaintext, decoder = self.decode(alter(first, offset) + end)
                self.assertEqual(plaintext, b"")
                self.assertTrue(decoder.errors)
                self.assertTrue(decoder.complete)
        # Tampering with the terminal tag must also make completion fail.
        plaintext, decoder = self.decode(first + alter(end, -1))
        self.assertEqual(plaintext, b"private")
        self.assertFalse(decoder.complete)
        self.assertTrue(decoder.errors)

    def test_wrong_key_machine_and_mode_do_not_release_plaintext(self):
        symbols = self.encode(b"secret")
        wrong_key = SealKey.from_dict({**KEY_DATA, "key_hex": "ff" * 32})
        data = self.machine.to_dict()
        data["rotors"]["VIII"]["notches"] = [3]
        for options in ({"key": wrong_key}, {"machine": Machine.from_dict(data)}):
            with self.subTest(options=options):
                plaintext, decoder = self.decode(symbols, **options)
                self.assertEqual(plaintext, b"")
                self.assertFalse(decoder.complete)
                self.assertTrue(decoder.errors)
        with self.assertRaises(SealStreamError):
            self.decode(symbols, mode="raw")
        plaintext, decoder = self.decode(self.encode(b"secret", mode="raw"))
        self.assertEqual(plaintext, b"")
        self.assertFalse(decoder.complete)
        self.assertTrue(decoder.errors)

    def test_loss_duplicate_reorder_damage_and_resynchronization(self):
        first, second, third, end = frames(self.encode(b"AAAABBBBCCCC", block_size=4))
        cases = (
            (first + third + end, b"AAAACCCC"),
            (first + first + second + third + end, b"AAAABBBBCCCC"),
            (second + first + third + end, b"BBBBCCCC"),
            (first + alter(second, 50) + third + end, b"AAAACCCC"),
            (first + second[:25] + third + end, b"AAAACCCC"),
            (first + "VVV(A?A)" + third + end, b"AAAACCCC"),
            (first + "VVV(" + "A" * (MAX_BODY + 1) + ")" + third + end, b"AAAACCCC"),
        )
        for symbols, expected in cases:
            with self.subTest(symbols=symbols[:60]):
                plaintext, decoder = self.decode(symbols)
                self.assertEqual(plaintext, expected)
                self.assertTrue(decoder.errors)
                self.assertTrue(decoder.complete)

    def test_raw_fails_immediately_on_loss_duplicate_and_damage(self):
        first, second, third, end = frames(self.encode(b"ABC", mode="raw", block_size=1))
        for symbols in (second, first + first, first + third, alter(first, 50), first[:12] + second, "?"):
            with self.subTest(symbols=symbols[:30]):
                decoder = SealDecoder(self.machine, self.key, mode="raw")
                with self.assertRaises(SealStreamError):
                    decoder.feed(symbols)
                self.assertGreater(decoder.error_count, 0)
                self.assertFalse(decoder.complete)
                with self.assertRaises(SealStreamError):
                    decoder.feed(end)
                with self.assertRaises(SealStreamError):
                    decoder.finish()

    def test_unauthenticated_session_and_sequence_cannot_change_receive_state(self):
        first, second, end = frames(self.encode(b"AB", block_size=1))
        for forged in (alter(second, 4), alter(second, 36)):
            decoder = SealDecoder(self.machine, self.key)
            self.assertEqual(decoder.feed(first), b"A")
            state = (decoder.session_id, decoder.expected_sequence, decoder.complete)
            self.assertEqual(decoder.feed(forged), b"")
            self.assertEqual((decoder.session_id, decoder.expected_sequence, decoder.complete), state)
            self.assertEqual(decoder.feed(second + end) + decoder.finish(), b"B")
            self.assertTrue(decoder.complete)
            self.assertEqual(decoder.error_count, 1)

    def test_empty_input_truncation_and_missing_end(self):
        for mode in ("checked", "raw"):
            symbols = self.encode(b"", mode=mode)
            plaintext, decoder = self.decode(symbols, mode=mode)
            self.assertEqual((plaintext, decoder.errors, decoder.complete), (b"", [], True))
        first, end = frames(self.encode(b"hi"))
        for symbols in ("", first, first + end[:-1], first + end + "VV", first + end + "VVV(A"):
            with self.subTest(symbols=symbols[-30:]):
                _, decoder = self.decode(symbols)
                self.assertFalse(decoder.complete)
                self.assertTrue(decoder.errors)
        raw_frame = frames(self.encode(b"hi", mode="raw"))[0]
        with self.assertRaises(SealStreamError):
            self.decode(raw_frame, mode="raw")

    def test_packet_bounds_noncanonical_base32_and_authenticated_invalid_ascii(self):
        symbols = self.encode(b"A" * 256, block_size=256)
        first = frames(symbols)[0]
        self.assertEqual(len(first) - 5, MAX_BODY)
        self.assertEqual(MAX_BODY, 516)
        # Even an authentic packet cannot carry values outside the ASCII contract.
        for invalid in (reference_frame(self.machine, b"\x80"), reference_frame(self.machine, b""),
                        reference_frame(self.machine, b"x", end=True), reference_frame(self.machine, b"x" * 257),
                        reference_frame(self.machine, b"x", sequence=MAX_SEQUENCE)):
            with self.subTest(invalid=invalid[:40]):
                plaintext, decoder = self.decode(invalid)
                self.assertEqual(plaintext, b"")
                self.assertTrue(decoder.errors)
        # Empty end envelope is 66 bytes: four final pad bits must be zero.
        end = frames(self.encode(b""))[0]
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        final = alphabet.index(end[-2])
        malformed = end[:-2] + alphabet[final ^ 1] + ")"
        plaintext, decoder = self.decode(malformed)
        self.assertEqual(plaintext, b"")
        self.assertFalse(decoder.complete)
        self.assertTrue(decoder.errors)

    def test_configuration_bounds_non_ascii_and_finished_state(self):
        for block_size in (0, 257, True, 1.5):
            with self.subTest(block_size=block_size), self.assertRaises(ValueError):
                SealEncoder(self.machine, self.key, block_size=block_size)
        for constructor in (SealEncoder, SealDecoder):
            with self.assertRaises(ValueError):
                constructor(self.machine, self.key, mode="invalid")
        encoder = SealEncoder(self.machine, self.key)
        with self.assertRaises(ValueError):
            encoder.feed(b"ok\xff")
        symbols = encoder.finish()
        self.assertEqual(self.decode(symbols)[0], b"")
        for operation in (lambda: encoder.feed(b"A"), encoder.flush, encoder.finish):
            with self.assertRaises(ValueError):
                operation()
        decoder = SealDecoder(self.machine, self.key)
        decoder.feed(symbols)
        decoder.finish()
        for operation in (lambda: decoder.feed(""), decoder.finish):
            with self.assertRaises(ValueError):
                operation()

    def test_session_randomness_and_sequence_exhaustion(self):
        one = frames(self.encode(b"same"))[0]
        two = frames(self.encode(b"same"))[0]
        self.assertNotEqual(unpack(one)[4:36], unpack(two)[4:36])
        self.assertNotEqual(unpack(one)[50:], unpack(two)[50:])
        for mode in ("checked", "raw"):
            encoder = SealEncoder(self.machine, self.key, mode=mode, block_size=1)
            encoder.sequence = MAX_SEQUENCE - 1
            data, end = encoder.feed(b"A"), encoder.finish()
            self.assertEqual(WIRE_HEADER.unpack_from(unpack(data))[4], MAX_SEQUENCE - 1)
            self.assertEqual(WIRE_HEADER.unpack_from(unpack(end))[4], MAX_SEQUENCE)
            encoder = SealEncoder(self.machine, self.key, mode=mode, block_size=1)
            encoder.sequence = MAX_SEQUENCE
            with self.assertRaisesRegex(ValueError, "sequence"):
                encoder.feed(b"A")

    def test_error_reporting_and_parser_memory_are_bounded(self):
        decoder = SealDecoder(self.machine, self.key)
        decoder.feed("(" + "A" * 100_000 + "(?)" * 1000)
        self.assertGreater(decoder.error_count, 100)
        self.assertLessEqual(len(decoder.errors), 129)
        self.assertTrue(decoder.body is None or len(decoder.body) <= MAX_BODY)
        plaintext = decoder.feed(self.encode(b"recovered")) + decoder.finish()
        self.assertEqual(plaintext, b"recovered")

    def test_completed_sessions_suppress_delayed_old_frames(self):
        older = self.encode(b"older")
        newer = self.encode(b"newer")
        plaintext, decoder = self.decode(older + newer + older)
        self.assertEqual(plaintext, b"oldernewer")
        self.assertTrue(decoder.errors)
        self.assertTrue(decoder.complete)

    def test_real_morse_wav_transport_requires_no_adapter_changes(self):
        from encrypted_radio.audio import AudioSettings, decode_wav, write_wav
        original = b"a+\n"
        symbols = self.encode(original)
        with tempfile.TemporaryDirectory() as directory:
            wav = Path(directory) / "sealed.wav"
            write_wav(wav, symbols, AudioSettings(sample_rate=44100, wpm=30), profile="checked")
            received, diagnostics = decode_wav(wav, profile="checked")
        self.assertEqual(diagnostics, [])
        self.assertEqual(received, symbols)
        plaintext, decoder = self.decode(received)
        self.assertEqual(plaintext, original)
        self.assertEqual(decoder.errors, [])


class SealCLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.key_path = self.path / "key.json"
        self.key_path.write_text(json.dumps(KEY_DATA), encoding="utf-8")

    def command(self, operation, *arguments):
        return [sys.executable, "-m", "encrypted_radio.seal_cli", operation,
                "--machine", str(ROOT / "examples/machine.json"), "--key", str(self.key_path), *arguments]

    def run_cli(self, operation, *arguments, data=None):
        return subprocess.run(self.command(operation, *arguments), input=data, capture_output=True, timeout=10)

    def test_batch_file_stdin_both_modes_and_status_codes(self):
        original = bytes(range(128))
        path = self.path / "input.dat"
        path.write_bytes(original)
        for mode in ("checked", "raw"):
            for arguments, data in (([], original), (["--input", str(path)], None), (["--text", "a +!\n"], None)):
                with self.subTest(mode=mode, arguments=arguments):
                    encrypted = self.run_cli("encrypt", "--mode", mode, *arguments, data=data)
                    self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
                    self.assertEqual(encrypted.stderr, b"")
                    actual = self.run_cli("decrypt", "--mode", mode, data=encrypted.stdout)
                    self.assertEqual(actual.returncode, 0, actual.stderr)
                    self.assertEqual(actual.stdout, b"a +!\n" if "--text" in arguments else original)
                    self.assertEqual(actual.stderr, b"")
            damaged = self.run_cli("decrypt", "--mode", mode, data=encrypted.stdout[:-1])
            self.assertEqual(damaged.returncode, 1, damaged.stderr)
            invalid = self.run_cli("encrypt", "--mode", mode, data=b"\xff")
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(invalid.stdout, b"")

    def test_keygen_private_permissions_no_stdout_and_no_overwrite(self):
        path = self.path / "nested" / "private" / "generated.json"
        command = [sys.executable, "-m", "encrypted_radio.seal_cli", "keygen", "--key", str(path)]
        result = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.parent.parent.stat().st_mode), 0o700)
        original = path.read_bytes()
        generated = load_key(path)
        self.assertNotEqual(generated.to_dict(), KEY_DATA)
        self.assertNotIn(generated.to_dict()["key_hex"].encode(), result.stderr)
        result = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(path.read_bytes(), original)
        alias = self.path / "alias.json"
        alias.symlink_to(path)
        result = subprocess.run(command[:-1] + [str(alias)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(path.read_bytes(), original)

    def test_argument_and_configuration_failures_are_clean(self):
        for arguments in (("--block-size", "0"), ("--block-size", "257"), ("--idle-seconds", "0"),
                          ("--idle-seconds", "nan"), ("--idle-seconds", "inf"), ("--text", "é")):
            result = self.run_cli("encrypt", *arguments, data=b"")
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout, b"")
            self.assertNotIn(b"Traceback", result.stderr)
        self.key_path.write_text(json.dumps({**KEY_DATA, "key_hex": "private-sentinel"}), encoding="utf-8")
        result = self.run_cli("encrypt", "--text", "a")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b"private-sentinel", result.stderr)

    def test_flags_before_operation_match_rotorcrypt_interface(self):
        command = [sys.executable, "-m", "encrypted_radio.seal_cli", "--machine",
                   str(ROOT / "examples/machine.json"), "--key", str(self.key_path),
                   "encrypt", "--text", "before operation"]
        encrypted = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(encrypted.returncode, 0, encrypted.stderr)
        decrypted = self.run_cli("decrypt", data=encrypted.stdout)
        self.assertEqual(decrypted.returncode, 0, decrypted.stderr)
        self.assertEqual(decrypted.stdout, b"before operation")

    def test_checked_idle_flush_and_raw_immediate_output_before_eof(self):
        for mode in ("checked", "raw"):
            with self.subTest(mode=mode):
                process = subprocess.Popen(self.command("encrypt", "--mode", mode, "--idle-seconds", "0.05"),
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    process.stdin.write(b"a")
                    process.stdin.flush()
                    ready, _, _ = select.select([process.stdout], [], [], 3)
                    self.assertTrue(ready, "encryption waited for EOF")
                    first = os.read(process.stdout.fileno(), 8192)
                    self.assertTrue(first.endswith(b")"), first)
                    # A pause longer than the configured idle interval changes no state.
                    time.sleep(0.15)
                    process.stdin.write(b"b")
                    process.stdin.close()
                    output = first + process.stdout.read()
                    self.assertEqual(process.wait(timeout=3), 0, process.stderr.read())
                    result = self.run_cli("decrypt", "--mode", mode, data=output)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, b"ab")
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    if not process.stdin.closed:
                        process.stdin.close()
                    process.stdout.close()
                    process.stderr.close()

    def test_decrypt_releases_verified_blocks_before_eof(self):
        machine, key = load_machine(), SealKey.from_dict(KEY_DATA)
        for mode in ("checked", "raw"):
            encoder = SealEncoder(machine, key, mode=mode, block_size=1)
            first, end = encoder.feed(b"a"), encoder.finish()
            process = subprocess.Popen(self.command("decrypt", "--mode", mode), stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                process.stdin.write(first.encode("ascii"))
                process.stdin.flush()
                ready, _, _ = select.select([process.stdout], [], [], 3)
                self.assertTrue(ready)
                self.assertEqual(os.read(process.stdout.fileno(), 1), b"a")
                process.stdin.write(end.encode("ascii"))
                process.stdin.close()
                self.assertEqual(process.wait(timeout=3), 0, process.stderr.read())
                self.assertEqual(process.stdout.read(), b"")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if not process.stdin.closed:
                    process.stdin.close()
                process.stdout.close()
                process.stderr.close()

    def test_broken_pipe_and_interrupt_status_without_traceback(self):
        process = subprocess.Popen(self.command("encrypt", "--mode", "raw"), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.stdout.close()
            process.stdin.write(b"A" * 4096)
            process.stdin.close()
            self.assertEqual(process.wait(timeout=3), 141)
            self.assertNotIn(b"Traceback", process.stderr.read())
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stderr.close()
        process = subprocess.Popen(self.command("encrypt", "--mode", "raw"), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.stdin.write(b"a")
            process.stdin.flush()
            ready, _, _ = select.select([process.stdout], [], [], 3)
            self.assertTrue(ready)
            os.read(process.stdout.fileno(), 8192)
            process.send_signal(signal.SIGINT)
            self.assertEqual(process.wait(timeout=3), 130)
            self.assertNotIn(b"Traceback", process.stderr.read())
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
