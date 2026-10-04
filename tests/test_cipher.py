"""Cipher, framing, and real subprocess streaming acceptance tests."""
import base64
from pathlib import Path
import select
import struct
import tempfile
import subprocess
import sys
import unittest
import zlib

from encrypted_radio.cipher import RawDecoder, RawEncoder, decrypt_text, encrypt_bytes
from encrypted_radio.codec import ASCIIDecoder, decode_ascii, encode_ascii
from encrypted_radio.config import ALPHABET, Key, Machine, load_key, load_machine
from encrypted_radio.framing import CheckedDecoder, CheckedEncoder, HEADER, MAX_BODY, MAX_SEQUENCE
from encrypted_radio.rotor import RotorMachine

ROOT = Path(__file__).resolve().parents[1]


def frames(text):
    return [part + ")" for part in text.split(")") if part]


def rewrite_frame(frame, change):
    body = frame[4:-1]
    packet = bytearray(base64.b32decode(body + "=" * (-len(body) % 8)))
    change(packet)
    packet[-4:] = struct.pack("!I", zlib.crc32(packet[:-4]))
    return "VVV(" + base64.b32encode(packet).decode().rstrip("=") + ")"


class CipherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.machine = load_machine()
        cls.key = load_key(machine=cls.machine)

    def test_all_ascii_codec_and_chunk_boundaries(self):
        original = bytes(range(128))
        encoded = encode_ascii(original)
        self.assertTrue(set(encoded) <= set(ALPHABET))
        self.assertEqual(decode_ascii(encoded), original)
        self.assertEqual(encode_ascii(b"A +a\x00"), "+61+20+2BA+00")
        self.assertEqual(encode_ascii(b"A +a\x00", text_encoding="uppercase-first"), "A+20+2B+61+00")
        for size in (1, 2, 3, 17, 128):
            decoder = ASCIIDecoder()
            actual = b"".join(decoder.feed(encoded[i:i+size]) for i in range(0, len(encoded), size))
            self.assertEqual(actual + decoder.finish(), original)
        for invalid in ("+", "+0", "+ff", "+80", "+GG", " ", "abc"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                decode_ascii(invalid)
        with self.assertRaisesRegex(ValueError, "ASCII"):
            encode_ascii(b"\x80")

    def test_configuration_roundtrip_and_validation(self):
        self.assertEqual(Machine.from_dict(self.machine.to_dict()).fingerprint, self.machine.fingerprint)
        self.assertEqual(Key.from_dict(self.key.to_dict(), self.machine), self.key)
        cases = [
            ("positions", [False, 1, 2]), ("positions", [49, 1, 2]),
            ("rings", [1]), ("rotors", ["I", "II"]),
            ("rotors", ["I", "II", "I"]), ("rotors", ["I", "II", "UNKNOWN"]),
            ("plugboard", ["AA"] * 12), ("plugboard", ["AB"] * 12),
            ("plugboard", list(self.key.plugboard)[:9]), ("version", True),
        ]
        for field, value in cases:
            invalid = self.key.to_dict()
            invalid[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                Key.from_dict(invalid, self.machine)
        for count in (10, 16):
            valid = self.key.to_dict()
            valid["plugboard"] = [ALPHABET[i:i+2] for i in range(0, count*2, 2)]
            self.assertEqual(len(Key.from_dict(valid, self.machine).plugboard), count)
        invalid = self.key.to_dict()
        invalid["plugboard"] = [ALPHABET[i:i+2] for i in range(0, 34, 2)]
        with self.assertRaisesRegex(ValueError, "10 to 16"):
            Key.from_dict(invalid, self.machine)
        invalid = self.machine.to_dict()
        invalid["reflector"] = ALPHABET
        with self.assertRaisesRegex(ValueError, "exactly one fixed"):
            Machine.from_dict(invalid)
        invalid = self.machine.to_dict()
        invalid["rotors"]["I"]["wiring"] = "A" * 49
        with self.assertRaisesRegex(ValueError, "permutation"):
            Machine.from_dict(invalid)
        invalid = self.machine.to_dict()
        invalid["rotors"]["I"]["notches"] = [1, 1]
        with self.assertRaisesRegex(ValueError, "unique"):
            Machine.from_dict(invalid)

    def test_analytical_affine_rotor_vector(self):
        # Independent algebra: rotors (2x+1,3x+2,5x+3), reflector48-x.
        # Before turnover the un-plugged composite is 36-x+18*step (mod49).
        machine = Machine.from_dict({"version": 1, "alphabet": ALPHABET, "rotors": {
            name: {"wiring": "".join(ALPHABET[(a*x+b) % 49] for x in range(49)), "notches": [47]}
            for name, a, b in [("A",2,1), ("B",3,2), ("C",5,3)]}, "reflector": ALPHABET[::-1]})
        key = Key.from_dict({"version": 1, "rotors": ["A", "B", "C"], "positions": [0,0,0],
                            "rings": [0,0,0], "plugboard": [ALPHABET[i:i+2] for i in range(0,20,2)]}, machine)
        expected = []
        plugs = lambda x: x ^ 1 if x < 20 else x
        for step, char in enumerate("ABCDEFGHIJ", 1):
            expected.append(ALPHABET[plugs((36-plugs(ALPHABET.index(char))+18*step) % 49)])
        rotor = RotorMachine(machine, key)
        self.assertEqual(rotor.transform("ABCDEFGHIJ"), "".join(expected))
        self.assertEqual(RotorMachine(machine, key).transform("".join(expected)), "ABCDEFGHIJ")

    def test_simultaneous_notches_double_step_and_ring_independence(self):
        data = self.machine.to_dict()
        data["rotors"]["II"]["notches"] = [5]
        data["rotors"]["III"]["notches"] = [0]
        machine = Machine.from_dict(data)
        data = self.key.to_dict()
        data["positions"] = [0,4,0]
        for rings in ([0,0,0], [4,25,48]):
            data["rings"] = rings
            rotor = RotorMachine(machine, Key.from_dict(data, machine))
            rotor.step()
            self.assertEqual(rotor.positions, [0,5,1])
            rotor.step()
            self.assertEqual(rotor.positions, [1,6,2])

    def test_all_stack_sizes_and_raw_streaming(self):
        data = bytes(range(128)) * 4
        for count in range(3, 9):
            config = self.key.to_dict()
            config.update(rotors=list(self.machine.rotors)[:count], positions=list(range(count)), rings=list(range(count-1,-1,-1)))
            key = Key.from_dict(config, self.machine)
            encoder = RawEncoder(self.machine, key)
            encrypted = "".join(encoder.feed(data[i:i+7]) for i in range(0,len(data),7)) + encoder.finish()
            decoder = RawDecoder(self.machine, key)
            recovered = b"".join(decoder.feed(c) for c in encrypted) + decoder.finish()
            self.assertEqual(recovered, data)

    def test_ring_settings_change_the_transform(self):
        data = self.key.to_dict()
        data["rings"][1] += 1
        other = Key.from_dict(data, self.machine)
        self.assertNotEqual(encrypt_bytes(b"HELLO", self.machine, self.key, "raw"), encrypt_bytes(b"HELLO", self.machine, other, "raw"))

    def test_checked_all_ascii_and_arbitrary_chunks(self):
        data = bytes(range(128)) * 4
        for block_size in (1, 7, 128, 256):
            encoder = CheckedEncoder(self.machine, self.key, block_size, b"TEST0001")
            text = "".join(encoder.feed(data[i:i+13]) for i in range(0,len(data),13)) + encoder.finish()
            decoder = CheckedDecoder(self.machine, self.key)
            actual = b"".join(decoder.feed(text[i:i+11]) for i in range(0,len(text),11)) + decoder.finish()
            self.assertEqual(actual, data)
            self.assertEqual(decoder.errors, [])
            self.assertTrue(decoder.complete)
        biggest = frames(encrypt_bytes(b"A"*256, self.machine, self.key, block_size=256))[0]
        self.assertEqual(len(biggest)-5, MAX_BODY)

    def test_no_plaintext_before_full_validated_block(self):
        text = encrypt_bytes(b"hello", self.machine, self.key)
        first = frames(text)[0]
        decoder = CheckedDecoder(self.machine, self.key)
        self.assertEqual(decoder.feed(first[:-1]), b"")
        self.assertEqual(decoder.feed(first[-1:]), b"hello")
        self.assertFalse(decoder.complete)
        decoder.finish()
        self.assertTrue(decoder.errors)

    def test_corruption_loss_duplicate_reorder_and_recovery(self):
        original = b"AAAABBBBCCCC"
        parts = frames(encrypt_bytes(original, self.machine, self.key, block_size=4))
        cases = [
            (parts[0] + parts[2] + parts[3], b"AAAACCCC"),
            (parts[0] + parts[1][:12] + "?" + parts[1][13:] + parts[2] + parts[3], b"AAAACCCC"),
            (parts[0] + parts[0] + "".join(parts[1:]), original),
            (parts[1] + parts[0] + parts[2] + parts[3], b"BBBBCCCC"),
            (parts[0] + parts[1][:20] + parts[2] + parts[3], b"AAAACCCC"),
            (parts[0] + "VVV(" + "A"*1288 + ")" + parts[2] + parts[3], b"AAAACCCC"),
        ]
        for text, expected in cases:
            with self.subTest(text=text[:80]):
                result = decrypt_text(text, self.machine, self.key)
                self.assertEqual(result.plaintext, expected)
                self.assertTrue(result.errors)
                self.assertTrue(result.complete)

    def test_wrong_key_machine_and_repaired_envelope_crc(self):
        text = encrypt_bytes(b"private testing payload", self.machine, self.key)
        key = self.key.to_dict()
        key["positions"][0] += 1
        result = decrypt_text(text, self.machine, Key.from_dict(key, self.machine))
        self.assertEqual(result.plaintext, b"")
        self.assertTrue(result.errors)
        machine = self.machine.to_dict()
        machine["rotors"]["VIII"]["notches"] = [3]
        result = decrypt_text(text, Machine.from_dict(machine), self.key)
        self.assertEqual(result.plaintext, b"")
        self.assertTrue(any("configuration" in e for e in result.errors))
        parts = frames(text)
        modified = rewrite_frame(parts[0], lambda packet: packet.__setitem__(HEADER.size, ord("A") if packet[HEADER.size] != ord("A") else ord("B")))
        result = decrypt_text(modified + parts[1], self.machine, self.key)
        self.assertEqual(result.plaintext, b"")
        self.assertTrue(result.errors)

    def test_header_limits_truncation_endframes_and_sequence_exhaustion(self):
        parts = frames(encrypt_bytes(b"ABCD", self.machine, self.key, block_size=2))
        for text in ("", parts[0], "".join(parts)[:-1], "".join(parts) + "VVV(A"):
            result = decrypt_text(text, self.machine, self.key)
            self.assertFalse(result.complete)
            self.assertTrue(result.errors)
        invalid = rewrite_frame(parts[0], lambda p: p.__setitem__(slice(18,20), b"\x04\x00"))
        result = decrypt_text(invalid + "".join(parts[1:]), self.machine, self.key)
        self.assertEqual(result.plaintext, b"CD")
        self.assertTrue(result.errors)
        empty = decrypt_text(encrypt_bytes(b"", self.machine, self.key), self.machine, self.key)
        self.assertEqual((empty.plaintext,empty.errors,empty.complete), (b"",[],True))
        encoder = CheckedEncoder(self.machine,self.key,1)
        encoder.sequence = MAX_SEQUENCE
        with self.assertRaisesRegex(ValueError,"sequence exhausted"):
            encoder.feed(b"A")

    def test_independent_blocks_public_only_fingerprint_and_sessions(self):
        encoder = CheckedEncoder(self.machine,self.key,1,b"TEST0001")
        first, second, end = encoder.feed(b"A"), encoder.feed(b"A"), encoder.finish()
        self.assertNotEqual(first,second)
        decoder = CheckedDecoder(self.machine,self.key)
        self.assertEqual(decoder.feed(second+end),b"A")
        self.assertTrue(any("missing frames 0" in e for e in decoder.errors))
        newer = encrypt_bytes(b"NEXT",self.machine,self.key,session_id=b"TEST0002")
        self.assertEqual(decoder.feed(newer+first),b"NEXT")
        self.assertTrue(any("superseded" in e for e in decoder.errors))
        decoder.finish()

    def test_outside_noise_and_trailing_preamble_are_reported(self):
        clean = encrypt_bytes(b"OK", self.machine, self.key)
        for noise in ("?", "\u00e9", " ", ")", "NOT A FRAME"):
            with self.subTest(noise=noise):
                before = decrypt_text(noise + clean, self.machine, self.key)
                after = decrypt_text(clean + noise, self.machine, self.key)
                self.assertEqual(before.plaintext, b"OK")
                self.assertEqual(after.plaintext, b"OK")
                self.assertTrue(before.errors)
                self.assertTrue(after.errors)
        truncated = decrypt_text(clean + "VV", self.machine, self.key)
        self.assertFalse(truncated.complete)
        self.assertTrue(any("preamble" in e for e in truncated.errors))
        # An opening delimiter can resynchronize even when training was lost.
        result = decrypt_text(clean.replace("VVV(", "("), self.machine, self.key)
        self.assertEqual(result.plaintext, b"OK")
        self.assertEqual(result.errors, [])

    def test_sequence_boundary_and_invalid_end_frame_shapes(self):
        encoder = CheckedEncoder(self.machine, self.key, 1, b"TEST0001")
        encoder.sequence = MAX_SEQUENCE - 1
        data, end = encoder.feed(b"A"), encoder.finish()
        decoder = CheckedDecoder(self.machine, self.key)
        result = decoder.feed(data + end)
        self.assertEqual(result, b"A")
        self.assertEqual(decoder.expected_sequence, MAX_SEQUENCE + 1)
        self.assertTrue(decoder.complete)
        parts = frames(encrypt_bytes(b"AB", self.machine, self.key))
        # A data-bearing frame cannot masquerade as an end marker.
        malformed = rewrite_frame(parts[0], lambda packet: packet.__setitem__(3, packet[3] | 1))
        result = decrypt_text(malformed + parts[1], self.machine, self.key)
        self.assertEqual(result.plaintext, b"")
        self.assertTrue(any("end frame" in e for e in result.errors))
        # Conversely an empty end frame cannot masquerade as data.
        malformed = rewrite_frame(parts[1], lambda packet: packet.__setitem__(3, packet[3] & ~1))
        result = decrypt_text(parts[0] + malformed, self.machine, self.key)
        self.assertFalse(result.complete)
        self.assertTrue(any("lengths" in e for e in result.errors))

    def test_reflector_noninvolution_and_config_read_limit(self):
        invalid = self.machine.to_dict()
        invalid["reflector"] = ALPHABET[1:] + ALPHABET[0]
        with self.assertRaisesRegex(ValueError, "reciprocal"):
            Machine.from_dict(invalid)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.json"
            path.write_bytes(b" " * 1_048_577)
            with self.assertRaisesRegex(ValueError, "exceeds 1 MiB"):
                load_machine(path)

    def test_bounded_parser_under_noise(self):
        decoder = CheckedDecoder(self.machine,self.key)
        decoder.feed("(" + "A"*50000 + "(?)"*1000)
        self.assertLessEqual(len(decoder.errors),129)
        self.assertTrue(decoder.body is None or len(decoder.body) <= 1287)


class CLITests(unittest.TestCase):
    def command(self, operation, *arguments):
        return [sys.executable, "-m", "encrypted_radio.rotor_cli", operation,
                "--machine", str(ROOT/"examples/machine.json"),
                "--key", str(ROOT/"examples/example-key.json"), *arguments]

    def test_cli_binary_ascii_roundtrip_and_error_exit(self):
        original = bytes(range(128))
        encrypted = subprocess.run(self.command("encrypt"),input=original,capture_output=True,check=True)
        result = subprocess.run(self.command("decrypt"),input=encrypted.stdout,capture_output=True,check=True)
        self.assertEqual(result.stdout,original)
        self.assertEqual(result.stderr,b"")
        damaged = subprocess.run(self.command("decrypt"),input=encrypted.stdout[:-1],capture_output=True)
        self.assertEqual(damaged.returncode,1)
        self.assertIn(b"missing session end",damaged.stderr)
        invalid = subprocess.run(self.command("encrypt"),input=b"\xff",capture_output=True)
        self.assertEqual(invalid.returncode,2)

    def test_checked_stdin_idle_flush_and_partial_input(self):
        process = subprocess.Popen(self.command("encrypt","--idle-seconds","0.1"),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            process.stdin.write(b"a")
            process.stdin.flush()
            ready,_,_ = select.select([process.stdout],[],[],3)
            self.assertTrue(ready,"checked input did not flush after idle timeout")
            first = process.stdout.read(1)
            self.assertEqual(first,b"V")
            process.stdin.write(b"b")
            process.stdin.close()
            output = first + process.stdout.read()
            self.assertEqual(process.wait(timeout=3),0)
            result = subprocess.run(self.command("decrypt"),input=output,capture_output=True,check=True)
            self.assertEqual(result.stdout,b"ab")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
            process.stderr.close()

    def test_broken_pipe_has_controlled_exit(self):
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

    def test_raw_stdin_outputs_before_eof(self):
        process = subprocess.Popen(self.command("encrypt","--mode","raw"),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            process.stdin.write(b"A")
            process.stdin.flush()
            ready,_,_ = select.select([process.stdout],[],[],3)
            self.assertTrue(ready)
            symbol = process.stdout.read(1)
            self.assertEqual(len(symbol),1)
            process.stdin.close()
            self.assertEqual(process.wait(timeout=3),0)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
