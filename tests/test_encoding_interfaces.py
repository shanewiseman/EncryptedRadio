"""Lowercase-first settings reach the shared cores across demo and browser I/O."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from aiohttp import FormData, WSMsgType
from aiohttp.test_utils import TestClient, TestServer
import numpy as np

from encrypted_radio import pipeline
from encrypted_radio.config import load_machine
from encrypted_radio.demo import main, run_roundtrip
from encrypted_radio.web import JOBS, create_app


ENCODING = "lowercase-first"


class EncodingDemoTests(unittest.TestCase):
    def test_default_preserves_case_with_every_cipher_mode_and_audio_transport(self):
        text = b"aA+\n"
        with tempfile.TemporaryDirectory() as directory:
            for cipher_name in pipeline.CIPHERS:
                for transport in pipeline.TRANSPORTS:
                    for mode in ("raw", "checked"):
                        with self.subTest(cipher=cipher_name, transport=transport, mode=mode):
                            result = run_roundtrip(text, cipher_name=cipher_name, transport=transport,
                                                   mode=mode,
                                                   output_dir=Path(directory))
                            self.assertTrue(result["success"], result["errors"])
                            self.assertEqual(result["recovered"].encode("ascii"), text)
                            self.assertEqual(result["received_symbols"], result["ciphertext"])
                            report = json.loads((Path(directory) / "report.json").read_text())
                            self.assertEqual(report["text_encoding"], ENCODING)

    def test_default_compacts_the_example_and_legacy_override_remains_available(self):
        text = b"This message is encrypted using wwii technology"
        machine = load_machine()
        key = pipeline.demo_key("rotorcrypt", machine)
        compact = pipeline.encrypt(text, machine, key, mode="raw")
        self.assertEqual(len(compact), 61)
        self.assertEqual(pipeline.decrypt(compact, machine, key, mode="raw").plaintext, text)
        for encoding in ("uppercase-first", "ascii"):
            legacy = pipeline.encrypt(text, machine, key, mode="raw", text_encoding=encoding)
            self.assertEqual(len(legacy), 139)
            self.assertEqual(pipeline.decrypt(legacy, machine, key, mode="raw",
                                              text_encoding=encoding).plaintext, text)

    def test_demo_cli_option_and_invalid_unencrypted_combination(self):
        with tempfile.TemporaryDirectory() as directory:
            for cipher_name in pipeline.CIPHERS:
                for flag, expected in (([], ENCODING), (["--uppercase-first"], "uppercase-first"),
                                       (["--text-encoding", "ascii"], "uppercase-first")):
                    with self.subTest(cipher=cipher_name, flag=flag), contextlib.redirect_stdout(io.StringIO()) as output:
                        with contextlib.redirect_stderr(io.StringIO()):
                            status = main(["roundtrip", "--text", "aA", "--mode", "raw",
                                           "--cipher", cipher_name, "--transport", "audiolink",
                                           "--output-dir", directory, *flag])
                        self.assertEqual(status, 0)
                        self.assertEqual(json.loads(output.getvalue())["text_encoding"], expected)
                        self.assertEqual((Path(directory) / "recovered.txt").read_bytes(), b"aA")
            with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
                status = main(["roundtrip", "--text", "abc", "--mode", "text",
                               "--text-encoding", ENCODING, "--output-dir", directory])
            self.assertEqual(status, 2)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("requires raw or checked", errors.getvalue())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
                main(["roundtrip", "--uppercase-first", "--text-encoding", ENCODING])
            self.assertEqual(failure.exception.code, 2)

    def test_pipeline_rejects_unknown_encoding_and_text_mode(self):
        machine = load_machine()
        key = pipeline.demo_key("rotorcrypt", machine)
        for mode, encoding in (("raw", "unknown"), ("text", ENCODING)):
            with self.subTest(mode=mode, encoding=encoding):
                with self.assertRaises(ValueError):
                    pipeline.encrypt(b"Ab", machine, key, mode=mode, text_encoding=encoding)
                with self.assertRaises(ValueError):
                    pipeline.decrypt("AB", machine, key, mode=mode, text_encoding=encoding)


class EncodingBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app()
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.config = await (await self.client.get("/api/config")).json()

    async def asyncTearDown(self):
        await self.client.close()

    def options(self, cipher_name="rotorcrypt", **kwargs):
        return {"cipher": cipher_name, "transport": "audiolink", "mode": "checked",
                "machine": self.config["machine"],
                "key": self.config["seal_key" if cipher_name == "sealcrypt" else "key"], **kwargs}

    async def test_encoding_validation_before_starting_work(self):
        self.assertEqual(self.config["text_encodings"], [ENCODING, "uppercase-first"])
        self.assertEqual(self.config["default_text_encoding"], ENCODING)
        for options in ({"text_encoding": "unknown"}, {"mode": "text", "text_encoding": ENCODING}, {"text_encoding": None}):
            data = self.options(text="abc", **options)
            response = await self.client.post("/api/roundtrip", json=data)
            self.assertEqual(response.status, 400)
            self.assertIn("encoding", (await response.json())["error"].lower())
            ws = await self.client.ws_connect(f"/api/live?session={uuid.uuid4()}")
            await ws.send_json({"type": "start", "operation": "rx", **data})
            self.assertEqual((await ws.receive_json(timeout=5))["type"], "error")
            await ws.close()
        self.assertEqual(self.app[JOBS], {})

    async def test_roundtrip_and_wav_upload_preserve_case_and_reject_mismatch(self):
        for cipher_name in pipeline.CIPHERS:
            with self.subTest(cipher=cipher_name):
                settings = self.options(cipher_name)
                response = await self.client.post("/api/roundtrip", json={**settings, "text": "aA+\n"})
                result = await response.json()
                self.assertEqual(response.status, 200, result)
                self.assertTrue(result["success"], result)
                self.assertEqual(result["text_encoding"], ENCODING)
                self.assertEqual(result["recovered"], "aA+\n")
                wav = await (await self.client.get(result["wav_url"])).read()
                for encoding in (None, "uppercase-first", "ascii"):
                    form = FormData()
                    selected = settings if encoding is None else {**settings, "text_encoding": encoding}
                    form.add_field("settings", json.dumps(selected))
                    form.add_field("audio", wav, filename="message.wav", content_type="audio/wav")
                    response = await self.client.post("/api/decode", data=form)
                    result = await response.json()
                    self.assertEqual(response.status, 200, result)
                    self.assertEqual(result["text_encoding"], ENCODING if encoding is None else "uppercase-first")
                    self.assertEqual(result["success"], encoding is None, result)
                    self.assertEqual(result["recovered"], "aA+\n" if encoding is None else "")

    async def test_streaming_tx_and_rx_preserve_case_for_both_ciphers_and_modes(self):
        # Actual generated PCM flows through both WebSocket directions. The
        # independent decrypt of announced symbols also checks TX preflight.
        machine = load_machine()
        for cipher_name in pipeline.CIPHERS:
            for mode in ("raw", "checked"):
                with self.subTest(cipher=cipher_name, mode=mode):
                    options = self.options(cipher_name, mode=mode)
                    tx = await self.client.ws_connect(f"/api/live?session={uuid.uuid4()}")
                    rx = await self.client.ws_connect(f"/api/live?session={uuid.uuid4()}")
                    await tx.send_json({"type": "start", "operation": "tx", "text": "aA",
                                        "streaming": True, **options})
                    ready = await tx.receive_json(timeout=5)
                    self.assertEqual(ready["type"], "ready", ready)
                    key = pipeline.demo_key(cipher_name, machine, options["key"])
                    preview = pipeline.stream_codec(mode, machine, key, receive=True,
                                                    cipher_name=cipher_name)
                    self.assertEqual(preview.feed(ready["symbols"]), b"aA")
                    await rx.send_json({"type": "start", "operation": "rx", **options})
                    self.assertEqual((await rx.receive_json(timeout=5))["type"], "ready")
                    await tx.send_json({"type": "begin"})
                    await tx.send_json({"type": "text", "text": " bB+\n"})
                    await tx.send_json({"type": "end"})
                    recovered = ""
                    samples = 0
                    while True:
                        event = await tx.receive(timeout=15)
                        if event.type == WSMsgType.BINARY:
                            pcm = np.frombuffer(event.data, dtype="<f4")
                            self.assertLessEqual(len(pcm), 48000 // 50)
                            samples += len(pcm)
                            await rx.send_bytes(event.data)
                            received = await rx.receive_json(timeout=5)
                            self.assertEqual(received["type"], "received", received)
                            self.assertEqual(received["ack"], len(pcm))
                            recovered += received["recovered"]
                            await tx.send_json({"type": "ack", "samples": len(pcm)})
                        elif event.type == WSMsgType.TEXT:
                            data = json.loads(event.data)
                            self.assertNotEqual(data["type"], "error", data)
                            if data["type"] == "complete":
                                self.assertAlmostEqual(data["duration"], samples / 48000)
                                break
                        else:
                            self.fail(str(event))
                    await rx.send_json({"type": "end"})
                    complete = await rx.receive_json(timeout=5)
                    self.assertTrue(complete["success"], complete)
                    self.assertEqual(recovered + complete["recovered"], "aA bB+\n")
                    await tx.close()
                    await rx.close()


if __name__ == "__main__":
    unittest.main()
