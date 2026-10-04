"""Reversible rotor text encodings and explicit checked-wire selection."""
import base64
from pathlib import Path
import struct
import subprocess
import sys
import unittest
import zlib

from encrypted_radio.cipher import RawDecoder, RawEncoder, decrypt_text, encrypt_bytes
from encrypted_radio.codec import (
    ASCIIDecoder, DEFAULT_TEXT_ENCODING, TEXT_ENCODINGS, decode_ascii, encode_ascii,
    normalize_text_encoding, validate_text_encoding,
)
from encrypted_radio.config import ALPHABET, load_key, load_machine
from encrypted_radio.framing import CheckedDecoder, CheckedEncoder, HEADER

ROOT = Path(__file__).resolve().parents[1]
MESSAGE = b"This message is encrypted using wwii technology"


def packets(stream):
    result = []
    for frame in stream.split(")")[:-1]:
        body = frame[4:]
        result.append(base64.b32decode(body + "=" * (-len(body) % 8)))
    return result


def change_flag(packet, flag):
    changed = bytearray(packet)
    changed[3] = flag
    changed[-4:] = struct.pack("!I", zlib.crc32(changed[:-4]))
    return "VVV(" + base64.b32encode(changed).decode("ascii").rstrip("=") + ")"


class TextEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.machine = load_machine()
        cls.key = load_key(machine=cls.machine)

    def test_codec_preserves_every_ascii_byte_across_escape_boundaries(self):
        original = bytes(range(128))
        for encoding in TEXT_ENCODINGS:
            encoded = encode_ascii(original, text_encoding=encoding)
            self.assertTrue(set(encoded) <= set(ALPHABET))
            self.assertEqual(decode_ascii(encoded, text_encoding=encoding), original)
            for size in (1, 2, 3, 7, 128):
                with self.subTest(encoding=encoding, chunk_size=size):
                    decoder = ASCIIDecoder(text_encoding=encoding)
                    recovered = b"".join(decoder.feed(encoded[i:i + size]) for i in range(0, len(encoded), size))
                    self.assertEqual(recovered + decoder.finish(), original)
        self.assertEqual(encode_ascii(b"A +a\x00", text_encoding="lowercase-first"), "+61+20+2BA+00")
        decoder = ASCIIDecoder(text_encoding="lowercase-first")
        self.assertEqual(decoder.feed("+6"), b"")
        self.assertEqual(decoder.feed("1A+4"), b"Aa")
        self.assertEqual(decoder.feed("1"), b"a")
        self.assertEqual(decoder.finish(), b"")

    def test_sample_preserves_case_and_reduces_raw_symbols_to_61(self):
        old = encrypt_bytes(MESSAGE, self.machine, self.key, "raw", text_encoding="uppercase-first")
        compact = encrypt_bytes(MESSAGE, self.machine, self.key, "raw")
        self.assertEqual((len(MESSAGE), len(old), len(compact)), (47, 139, 61))
        self.assertEqual(compact, encrypt_bytes(MESSAGE, self.machine, self.key, "raw", text_encoding="lowercase-first"))
        decoded = decrypt_text(compact, self.machine, self.key, "raw")
        self.assertEqual((decoded.plaintext, decoded.errors, decoded.complete), (MESSAGE, [], True))

    def test_uppercase_first_and_ascii_alias_preserve_legacy_vectors(self):
        expected = {
            "raw": "ZNCVI4T55I)LB",
            "checked": ("VVV(IVJACACUIVJVIMBQGAYQAAAAAAAAKAANVOYTRT22SK4AMS353I6VANRZIVJUURSAKNCEMWBHHLEAQZI)"
                        "VVV(IVJACAKUIVJVIMBQGAYQAAAAAEAAAAAAVOYTRT22SK4AMAAAAAAD64OOWQ)"),
        }
        original = b"A +a\x00"
        for mode, vector in expected.items():
            with self.subTest(mode=mode):
                self.assertEqual(encrypt_bytes(original, self.machine, self.key, mode, session_id=b"TEST0001", text_encoding="uppercase-first"), vector)
                self.assertEqual(encrypt_bytes(original, self.machine, self.key, mode, session_id=b"TEST0001", text_encoding="ascii"), vector)
                for encoding in ("uppercase-first", "ascii"):
                    self.assertEqual(decrypt_text(vector, self.machine, self.key, mode, text_encoding=encoding).plaintext, original)

    def test_encoding_alias_is_normalized_in_incremental_cores(self):
        self.assertEqual(DEFAULT_TEXT_ENCODING, "lowercase-first")
        self.assertEqual(normalize_text_encoding("ascii"), "uppercase-first")
        self.assertEqual(encode_ascii(b"aA"), "A+61")
        self.assertEqual(decode_ascii("A+61"), b"aA")
        self.assertEqual(encode_ascii(b"aA", text_encoding="ascii"), "+61A")
        for constructor in (RawEncoder, CheckedEncoder, CheckedDecoder):
            self.assertEqual(constructor(self.machine, self.key, text_encoding="ascii").text_encoding, "uppercase-first")
            self.assertEqual(constructor(self.machine, self.key).text_encoding, "lowercase-first")
        self.assertEqual(ASCIIDecoder(text_encoding="ascii").text_encoding, "uppercase-first")
        self.assertEqual(RawDecoder(self.machine, self.key, text_encoding="ascii").codec.text_encoding, "uppercase-first")

    def test_raw_streams_keep_state_across_all_ascii_chunks(self):
        original = bytes(range(128)) * 2
        encoder = RawEncoder(self.machine, self.key)
        ciphertext = "".join(encoder.feed(original[i:i + 7]) for i in range(0, len(original), 7)) + encoder.finish()
        self.assertEqual(ciphertext, encrypt_bytes(original, self.machine, self.key, "raw", text_encoding="lowercase-first"))
        decoder = RawDecoder(self.machine, self.key)
        self.assertEqual(b"".join(decoder.feed(symbol) for symbol in ciphertext) + decoder.finish(), original)

    def test_raw_mismatched_encoding_can_silently_invert_case(self):
        # Raw has no encoding marker or integrity check: callers must match it.
        ciphertext = encrypt_bytes(MESSAGE, self.machine, self.key, "raw", text_encoding="lowercase-first")
        decoded = decrypt_text(ciphertext, self.machine, self.key, "raw", text_encoding="uppercase-first")
        self.assertEqual((decoded.plaintext, decoded.errors, decoded.complete), (MESSAGE.swapcase(), [], True))

    def test_checked_flags_and_crc_cover_original_plaintext(self):
        encoder = CheckedEncoder(self.machine, self.key)
        stream = encoder.feed(MESSAGE) + encoder.finish()
        data, end = packets(stream)
        header = HEADER.unpack_from(data)
        self.assertEqual((header[2], header[5], header[6], header[8]), (2, 47, 61, zlib.crc32(MESSAGE)))
        self.assertEqual(HEADER.unpack_from(end)[2], 3)
        decoder = CheckedDecoder(self.machine, self.key)
        first_end = stream.index(")")
        self.assertEqual(decoder.feed(stream[:first_end]), b"")
        self.assertEqual(decoder.feed(stream[first_end:]), MESSAGE)
        self.assertEqual(decoder.finish(), b"")
        self.assertEqual((decoder.errors, decoder.complete), ([], True))

    def test_checked_all_ascii_chunked_roundtrip_and_empty_end(self):
        original = bytes(range(128)) * 2
        for block_size in (1, 17, 128, 256):
            with self.subTest(block_size=block_size):
                encoder = CheckedEncoder(self.machine, self.key, block_size)
                stream = "".join(encoder.feed(original[i:i + 11]) for i in range(0, len(original), 11)) + encoder.finish()
                decoder = CheckedDecoder(self.machine, self.key)
                recovered = b"".join(decoder.feed(stream[i:i + 7]) for i in range(0, len(stream), 7)) + decoder.finish()
                self.assertEqual((recovered, decoder.errors, decoder.complete), (original, [], True))
        stream = encrypt_bytes(b"", self.machine, self.key, text_encoding="lowercase-first")
        self.assertEqual(HEADER.unpack_from(packets(stream)[0])[2], 3)
        decoded = decrypt_text(stream, self.machine, self.key, text_encoding="lowercase-first")
        self.assertEqual((decoded.plaintext, decoded.errors, decoded.complete), (b"", [], True))

    def test_checked_mismatch_releases_nothing_and_does_not_update_session(self):
        # Numeric-only text also requires the selected encoding to match.
        for sender, receiver in (("uppercase-first", "lowercase-first"), ("lowercase-first", "uppercase-first")):
            with self.subTest(sender=sender):
                stream = encrypt_bytes(b"123", self.machine, self.key, text_encoding=sender)
                decoder = CheckedDecoder(self.machine, self.key, text_encoding=receiver)
                self.assertEqual(decoder.feed(stream), b"")
                self.assertEqual((decoder.session_id, decoder.expected_sequence, decoder.complete), (None, 0, False))
                decoder.finish()
                self.assertTrue(any("text encoding" in error for error in decoder.errors))
                self.assertFalse(decoder.complete)

    def test_changed_encoding_flag_cannot_bypass_plaintext_crc(self):
        stream = encrypt_bytes(MESSAGE, self.machine, self.key, text_encoding="lowercase-first")
        data, end = packets(stream)
        # Repair the envelope CRC after clearing the flag, but keep original CRC.
        decoded = decrypt_text(change_flag(data, 0) + change_flag(end, 1), self.machine, self.key, text_encoding="uppercase-first")
        self.assertEqual(decoded.plaintext, b"")
        self.assertTrue(any("plaintext checksum mismatch" in error for error in decoded.errors))

    def test_unknown_flags_and_mismatched_end_are_rejected(self):
        stream = encrypt_bytes(MESSAGE, self.machine, self.key, text_encoding="lowercase-first")
        data, end = packets(stream)
        invalid = decrypt_text(change_flag(data, 6) + change_flag(end, 3), self.machine, self.key, text_encoding="lowercase-first")
        self.assertEqual(invalid.plaintext, b"")
        self.assertTrue(any("unsupported checked frame header" in error for error in invalid.errors))
        mismatched_end = decrypt_text(change_flag(data, 2) + change_flag(end, 1), self.machine, self.key, text_encoding="lowercase-first")
        self.assertEqual(mismatched_end.plaintext, MESSAGE)
        self.assertFalse(mismatched_end.complete)
        self.assertTrue(any("text encoding" in error for error in mismatched_end.errors))

    def test_invalid_encoding_and_non_ascii_are_rejected(self):
        factories = (
            lambda value: validate_text_encoding(value),
            lambda value: normalize_text_encoding(value),
            lambda value: encode_ascii(b"", text_encoding=value),
            lambda value: decode_ascii("", text_encoding=value),
            lambda value: ASCIIDecoder(text_encoding=value),
            lambda value: RawEncoder(self.machine, self.key, text_encoding=value),
            lambda value: RawDecoder(self.machine, self.key, text_encoding=value),
            lambda value: CheckedEncoder(self.machine, self.key, text_encoding=value),
            lambda value: CheckedDecoder(self.machine, self.key, text_encoding=value),
            lambda value: encrypt_bytes(b"", self.machine, self.key, text_encoding=value),
            lambda value: decrypt_text("", self.machine, self.key, text_encoding=value),
        )
        for invalid in ("lowercase", "", None, 1):
            for factory in factories:
                with self.subTest(invalid=invalid, factory=factory), self.assertRaisesRegex(ValueError, "text encoding"):
                    factory(invalid)
        for encoding in TEXT_ENCODINGS:
            with self.assertRaisesRegex(ValueError, "ASCII"):
                encode_ascii(b"\x80", text_encoding=encoding)
            for mode in ("raw", "checked"):
                with self.assertRaisesRegex(ValueError, "ASCII"):
                    encrypt_bytes(b"\xff", self.machine, self.key, mode, text_encoding=encoding)
            for invalid in ("+", "+0", "+ff", "+80", "+GG", " ", "abc"):
                with self.subTest(encoding=encoding, invalid=invalid), self.assertRaises(ValueError):
                    decode_ascii(invalid, text_encoding=encoding)

    def test_cli_roundtrip_and_checked_selection_failure(self):
        command = [sys.executable, "-m", "encrypted_radio.rotor_cli"]
        options = ["--machine", str(ROOT / "examples/machine.json"), "--key", str(ROOT / "examples/example-key.json")]
        for mode in ("raw", "checked"):
            for flags in ([], ["--uppercase-first"], ["--text-encoding", "uppercase-first"], ["--text-encoding", "ascii"]):
                with self.subTest(mode=mode, flags=flags):
                    selected = options + ["--mode", mode] + flags
                    encrypted = subprocess.run(command + ["encrypt"] + selected, input=bytes(range(128)), capture_output=True, check=True)
                    decrypted = subprocess.run(command + ["decrypt"] + selected, input=encrypted.stdout, capture_output=True, check=True)
                    self.assertEqual((decrypted.stdout, decrypted.stderr), (bytes(range(128)), b""))
                    if mode == "checked":
                        expected_flag = 0 if flags else 2
                        self.assertEqual(HEADER.unpack_from(packets(encrypted.stdout.decode("ascii"))[0])[2], expected_flag)
        # The last stream uses legacy encoding; an unconfigured receiver now expects lowercase-first.
        mismatch = subprocess.run(command + ["decrypt"] + options, input=encrypted.stdout, capture_output=True)
        self.assertEqual((mismatch.returncode, mismatch.stdout), (1, b""))
        self.assertIn(b"text encoding", mismatch.stderr)

    def test_cli_default_size_uppercase_shorthand_and_conflicting_options(self):
        command = [sys.executable, "-m", "encrypted_radio.rotor_cli"]
        options = ["--machine", str(ROOT / "examples/machine.json"), "--key", str(ROOT / "examples/example-key.json"), "--mode", "raw"]
        for flags, length in (([], 61), (["--uppercase-first"], 139)):
            encrypted = subprocess.run(command + ["encrypt"] + options + flags, input=MESSAGE, capture_output=True, check=True)
            self.assertEqual(len(encrypted.stdout), length)
        for operation in ("encrypt", "decrypt"):
            result = subprocess.run(command + [operation] + options + ["--uppercase-first", "--text-encoding", "lowercase-first"],
                                    input=b"", capture_output=True)
            self.assertEqual((result.returncode, result.stdout), (2, b""))
            self.assertIn(b"not allowed with argument", result.stderr)


if __name__ == "__main__":
    unittest.main()
