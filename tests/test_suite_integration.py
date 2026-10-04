"""Independent cipher/transport selections exercise the real waveform path."""
import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import wave

from aiohttp import FormData, WSMsgType
from aiohttp.test_utils import TestClient, TestServer
import numpy as np

from encrypted_radio import pipeline, seal
from encrypted_radio.config import load_machine
from encrypted_radio.demo import LOSS_TEXT, run_roundtrip
from encrypted_radio.web import SESSIONS, TEMP_ROOT, create_app


class SuiteDemoTests(unittest.TestCase):
    def test_all_cipher_transport_pairs_checked_and_raw(self):
        text = b"Hi!\n+a"
        with tempfile.TemporaryDirectory() as directory:
            for cipher_name in pipeline.CIPHERS:
                for transport in pipeline.TRANSPORTS:
                    for mode in ("checked", "raw"):
                        with self.subTest(cipher=cipher_name, transport=transport, mode=mode):
                            result = run_roundtrip(text, cipher_name=cipher_name, transport=transport,
                                                   mode=mode, output_dir=Path(directory))
                            self.assertTrue(result["success"], result["errors"])
                            self.assertEqual(result["recovered"].encode("ascii"), text)
                            self.assertEqual(result["received_symbols"], result["ciphertext"])
                            self.assertEqual((result["cipher"], result["transport"]), (cipher_name, transport))

    def test_seal_morse_and_both_packet_ciphers_recover_after_actual_pcm_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            for cipher_name, transport in (("sealcrypt", "morselink"), ("rotorcrypt", "audiolink"), ("sealcrypt", "audiolink")):
                with self.subTest(cipher=cipher_name, transport=transport):
                    result = run_roundtrip(LOSS_TEXT, cipher_name=cipher_name, transport=transport,
                                           scenario="lost-block", output_dir=Path(directory))
                    self.assertTrue(result["success"], result["errors"])
                    self.assertFalse(result["matched"])
                    self.assertEqual(result["recovered"].encode(), LOSS_TEXT[:16] + LOSS_TEXT[32:])
                    self.assertTrue(result["pcm_segments"][1]["removed"])

    def test_packet_noise_and_text_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode, text in (("checked", b"Meet at 09:30!\n"), ("text", b" hello\n  world ")):
                result = run_roundtrip(text, mode=mode, cipher_name="sealcrypt", transport="audiolink",
                                       scenario="noisy", output_dir=Path(directory))
                self.assertTrue(result["success"], result["errors"])
                self.assertIn("AFSKDecoder", result["decoder"])


class SuiteBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app()
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.config = await (await self.client.get("/api/config")).json()

    async def asyncTearDown(self):
        root = self.app[TEMP_ROOT]
        await self.client.close()
        self.assertFalse(root.exists())

    def options(self, cipher_name="sealcrypt", **kwargs):
        return {"cipher": cipher_name, "transport": "audiolink", "mode": "checked",
                "machine": self.config["machine"],
                "key": self.config["seal_key" if cipher_name == "sealcrypt" else "key"], **kwargs}

    async def test_key_generation_and_selection_validation(self):
        original = self.config["seal_key"]
        generated = await self.client.post("/api/seal-key", json={})
        self.assertEqual(generated.status, 200)
        other = (await generated.json())["seal_key"]
        self.assertNotEqual(original["key_hex"], other["key_hex"])
        seal.SealKey.from_dict(other)
        self.assertEqual(generated.headers["Cache-Control"], "no-store")
        for options in ({"cipher": "unknown"}, {"transport": "unknown"}, {"cipher": "sealcrypt"},
                        {"transport": "audiolink", "wpm": 30},
                        {"cipher": "sealcrypt", "key": self.config["key"]},
                        {"cipher": "rotorcrypt", "key": original}):
            response = await self.client.post("/api/roundtrip", json={"text": "HI", **options})
            self.assertEqual(response.status, 400, options)
        response = await self.client.post("/api/seal-key", json={"path": "/tmp/key"})
        self.assertEqual(response.status, 400)

    async def test_selected_roundtrips_and_key_free_artifacts(self):
        for cipher_name, transport in (("sealcrypt", "morselink"), ("rotorcrypt", "audiolink"), ("sealcrypt", "audiolink")):
            response = await self.client.post("/api/roundtrip", json=self.options(cipher_name, transport=transport, text="Hi!\n"))
            result = await response.json()
            self.assertEqual(response.status, 200, result)
            self.assertTrue(result["success"], result)
            self.assertEqual(result["recovered"], "Hi!\n")
            self.assertNotIn(self.config["seal_key"]["key_hex"], json.dumps(result))
            self.assertFalse(any("key" in name for name in result["downloads"]))
            report = await (await self.client.get(result["downloads"]["report.json"])).text()
            self.assertNotIn(self.config["seal_key"]["key_hex"], report)

    async def test_packet_wav_upload_both_rates_and_wrong_key(self):
        from encrypted_radio.packet_audio import AFSKSettings, AFSKEncoder
        machine = load_machine()
        key = seal.SealKey.from_dict(self.config["seal_key"])
        for rate in (44100, 48000):
            symbols = pipeline.encrypt(b"a\n+", machine, key, cipher_name="sealcrypt")
            encoder = AFSKEncoder(AFSKSettings(sample_rate=rate))
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
                for pcm in (*encoder.feed(symbols), *encoder.finish()):
                    output.writeframesraw((pcm * 32767).astype("<i2").tobytes())
            for wrong in (False, True):
                settings = self.options()
                if wrong:
                    settings["key"] = seal.generate_key().to_dict()
                form = FormData()
                form.add_field("settings", json.dumps(settings))
                form.add_field("audio", buffer.getvalue(), filename="packet.wav", content_type="audio/wav")
                response = await self.client.post("/api/decode", data=form)
                result = await response.json()
                self.assertEqual(response.status, 200, result)
                self.assertEqual(result["recovered"], "" if wrong else "a\n+")
                self.assertEqual(result["success"], not wrong)

    async def test_live_packet_transmission_roundtrip_duration_and_streaming(self):
        # Receive the actual WebSocket PCM with an independent shared decoder.
        for rate, streaming, mode in ((44100, False, "checked"), (48000, True, "raw")):
            session = str(uuid.uuid4())
            ws = await self.client.ws_connect(f"/api/live?session={session}")
            await ws.send_json({"type": "start", "operation": "tx", "text": "Hello", "streaming": streaming,
                                **self.options(sample_rate=rate, mode=mode)})
            ready = await ws.receive_json(timeout=10)
            self.assertEqual(ready["type"], "ready", ready)
            await ws.send_json({"type": "begin"})
            if streaming:
                await ws.send_json({"type": "text", "text": " again!\n"})
                await ws.send_json({"type": "end"})
            decoder = pipeline.audio_decoder("audiolink", rate, mode)
            symbols, samples, idle_events = "", 0, 0
            while True:
                event = await ws.receive(timeout=15)
                if event.type == WSMsgType.BINARY:
                    pcm = np.frombuffer(event.data, dtype="<f4")
                    self.assertLessEqual(len(pcm), rate // 50)
                    samples += len(pcm)
                    symbols += decoder.feed(pcm)
                    await ws.send_json({"type": "ack", "samples": len(pcm)})
                elif event.type == WSMsgType.TEXT:
                    data = json.loads(event.data)
                    self.assertNotEqual(data["type"], "error", data)
                    idle_events += data["type"] == "idle"
                    if data["type"] == "complete":
                        self.assertAlmostEqual(data["duration"], samples / rate)
                        break
                else:
                    self.fail(str(event))
            symbols += decoder.finish()
            self.assertEqual(decoder.diagnostics, [])
            result = pipeline.decrypt(symbols, load_machine(), seal.SealKey.from_dict(self.config["seal_key"]),
                                      cipher_name="sealcrypt", mode=mode)
            self.assertEqual(result.errors, [])
            self.assertEqual(result.plaintext, b"Hello again!\n" if streaming else b"Hello")
            if streaming:
                self.assertGreater(idle_events, 0)
            else:
                self.assertAlmostEqual(ready["duration"], samples / rate)
            await ws.close()
            for _ in range(100):
                if session not in self.app[SESSIONS]:
                    break
                await asyncio.sleep(.01)
            self.assertNotIn(session, self.app[SESSIONS])

    async def test_streaming_ready_duration_matches_initial_pcm_for_both_transports_and_rates(self):
        # A streaming preview excludes unsent transport EOF/end audio. Measure
        # the actual first WebSocket burst through its explicit idle boundary.
        for transport in pipeline.TRANSPORTS:
            for rate in (44100, 48000):
                with self.subTest(transport=transport, rate=rate):
                    session = str(uuid.uuid4())
                    ws = await self.client.ws_connect(f"/api/live?session={session}")
                    await ws.send_json({
                        "type": "start", "operation": "tx", "text": "HELLO",
                        "streaming": True,
                        **self.options(transport=transport, sample_rate=rate, mode="text"),
                    })
                    ready = await ws.receive_json(timeout=5)
                    self.assertEqual(ready["type"], "ready", ready)
                    await ws.send_json({"type": "begin"})
                    samples = 0
                    while True:
                        event = await ws.receive(timeout=10)
                        if event.type == WSMsgType.BINARY:
                            count = len(event.data) // 4
                            samples += count
                            await ws.send_json({"type": "ack", "samples": count})
                        elif event.type == WSMsgType.TEXT:
                            data = json.loads(event.data)
                            self.assertNotEqual(data["type"], "error", data)
                            if data["type"] == "idle":
                                break
                        else:
                            self.fail(str(event))
                    self.assertGreater(samples, 0)
                    self.assertAlmostEqual(ready["duration"], samples / rate, places=10)
                    await ws.send_json({"type": "stop"})
                    await ws.close()
                    for _ in range(100):
                        if session not in self.app[SESSIONS]:
                            break
                        await asyncio.sleep(.01)
                    self.assertNotIn(session, self.app[SESSIONS])

    async def test_live_packet_receive_sample_rates_and_discontinuity(self):
        from encrypted_radio.packet_audio import AFSKEncoder, AFSKSettings
        for rate in (44100, 48000):
            session = str(uuid.uuid4())
            ws = await self.client.ws_connect(f"/api/live?session={session}")
            await ws.send_json({"type": "start", "operation": "rx", **self.options(sample_rate=rate)})
            self.assertEqual((await ws.receive_json(timeout=5))["type"], "ready")
            symbols = pipeline.encrypt(b"Live\n", load_machine(), seal.SealKey.from_dict(self.config["seal_key"]), cipher_name="sealcrypt")
            encoder = AFSKEncoder(AFSKSettings(sample_rate=rate))
            received = ""
            for pcm in (*encoder.feed(symbols), *encoder.finish()):
                await ws.send_bytes(pcm.astype("<f4").tobytes())
                event = await ws.receive_json(timeout=5)
                self.assertEqual(event["ack"], len(pcm))
                received += event["recovered"]
            await ws.send_json({"type": "end"})
            event = await ws.receive_json(timeout=5)
            self.assertTrue(event["success"], event)
            self.assertEqual(received + event["recovered"], "Live\n")
            await ws.close()
            self.assertNotIn(session, self.app[SESSIONS])
        ws = await self.client.ws_connect(f"/api/live?session={uuid.uuid4()}")
        await ws.send_json({"type": "start", "operation": "rx", **self.options(mode="raw")})
        self.assertEqual((await ws.receive_json(timeout=5))["type"], "ready")
        await ws.send_json({"type": "discontinuity"})
        self.assertEqual((await ws.receive_json(timeout=5))["type"], "error")
        await ws.close()


if __name__ == "__main__":
    unittest.main()
