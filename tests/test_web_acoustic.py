"""Synthetic duplex PCM fixtures; these do not establish physical audio compatibility."""

import asyncio
import json
import re
import unittest
import uuid
from unittest.mock import patch

import numpy as np
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from encrypted_radio import pipeline
from encrypted_radio.web import SESSIONS, create_app


class AcousticBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app()
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def start_socket(self, **options):
        session = str(uuid.uuid4())
        ws = await self.client.ws_connect(f"/api/live?session={session}")
        settings = {"type": "start", "operation": "acoustic", "mode": "raw",
                    "cipher": "rotorcrypt", "transport": "morselink", "text": "Hi!\n",
                    "sample_rate": 48000, **options}
        if settings["transport"] == "morselink":
            settings.update(frequency=700, wpm=30, rx_frequency=700, rx_wpm=30)
        if settings["cipher"] == "sealcrypt":
            # Fixed public fixture key, never a private communication key.
            settings["key"] = {"version": 1, "algorithm": "chacha20-poly1305", "key_hex": "12" * 32}
        await ws.send_json(settings)
        ready = await ws.receive_json(timeout=5)
        self.assertEqual(ready["type"], "ready", ready)
        self.assertEqual(ready["operation"], "acoustic")
        self.assertFalse(ready["streaming"])
        return ws, session, ready

    async def receive_event(self, ws):
        event = await ws.receive(timeout=10)
        self.assertIn(event.type, (WSMsgType.TEXT, WSMsgType.BINARY), event)
        if event.type == WSMsgType.BINARY:
            return event.data
        data = json.loads(event.data)
        self.assertNotEqual(data["type"], "error", data)
        return data

    async def drain_transmission(self, ws, *, capture=True):
        """Only the test client feeds emitted PCM back as synthetic microphone input."""
        await ws.send_json({"type": "begin"})
        samples, acknowledged = 0, 0
        symbols, recovered = [], []
        while True:
            data = await self.receive_event(ws)
            if isinstance(data, bytes):
                count = len(data) // 4
                samples += count
                if capture:
                    await ws.send_bytes(data)
                await ws.send_json({"type": "ack", "samples": count})
            elif data["type"] == "received":
                acknowledged += data["ack"]
                symbols.append(data["symbols"])
                recovered.append(data["recovered"])
            elif data["type"] == "transmitted":
                self.assertEqual(acknowledged, samples if capture else 0)
                self.assertFalse(ws.closed, "Playback completion must leave microphone reception alive.")
                return samples, "".join(symbols), "".join(recovered), data
            else:
                self.assertIn(data["type"], ("symbols", "draining"), data)

    async def finish_reception(self, ws, *, rate=48000, silence=True):
        if silence:
            await ws.send_bytes(np.zeros(rate, dtype="<f4").tobytes())
        await ws.send_json({"type": "end"})
        symbols, recovered = [], []
        while True:
            data = await self.receive_event(ws)
            self.assertIsInstance(data, dict)
            self.assertIn(data["type"], ("received", "complete"), data)
            symbols.append(data["symbols"])
            recovered.append(data["recovered"])
            if data["type"] == "complete":
                return "".join(symbols), "".join(recovered), data

    async def test_pcm_roundtrip_all_cipher_transport_and_mode_combinations(self):
        for cipher in pipeline.CIPHERS:
            for transport in pipeline.TRANSPORTS:
                for mode in ("raw", "checked"):
                    for encoding, rate in (("lowercase-first", 48000), ("uppercase-first", 44100)):
                        with self.subTest(cipher=cipher, transport=transport, mode=mode, encoding=encoding):
                            ws, session, ready = await self.start_socket(cipher=cipher, transport=transport, mode=mode,
                                                                         text_encoding=encoding, sample_rate=rate)
                            # Capture starts before begin; this cannot advance the TX cipher or sample count.
                            await ws.send_bytes(np.zeros(rate // 10, dtype="<f4").tobytes())
                            self.assertEqual((await ws.receive_json(timeout=5))["ack"], rate // 10)
                            samples, symbols, recovered, transmitted = await self.drain_transmission(ws)
                            tail_symbols, tail_recovered, result = await self.finish_reception(ws, rate=rate)
                            self.assertEqual(symbols + tail_symbols, ready["symbols"])
                            self.assertEqual(recovered + tail_recovered, "Hi!\n")
                            self.assertTrue(result["matched"], result)
                            self.assertTrue(result["complete"], result)
                            self.assertTrue(result["success"], result)
                            self.assertEqual(result["errors"], [])
                            self.assertAlmostEqual(result["duration"], samples / rate)
                            self.assertEqual(result["duration"], transmitted["duration"])
                            await ws.close()
                            self.assertNotIn(session, self.app[SESSIONS])

    async def test_text_mode_matches_shared_normalization_at_44100_hz(self):
        for transport in pipeline.TRANSPORTS:
            with self.subTest(transport=transport):
                ws, _, _ = await self.start_socket(mode="text", transport=transport,
                                                   sample_rate=44100, text=" \tHi\n  there. \r")
                samples, _, recovered, _ = await self.drain_transmission(ws)
                _, tail, result = await self.finish_reception(ws, rate=44100)
                self.assertEqual(recovered + tail, "HI THERE.")
                self.assertTrue(result["matched"], result)
                self.assertTrue(result["success"], result)
                self.assertAlmostEqual(result["duration"], samples / 44100)
                await ws.close()

    async def test_silence_never_uses_transmitted_plaintext_as_reception(self):
        for cipher, transport, mode in (("rotorcrypt", "morselink", "raw"),
                                        ("rotorcrypt", "audiolink", "checked"),
                                        ("sealcrypt", "morselink", "raw")):
            with self.subTest(cipher=cipher, transport=transport, mode=mode):
                ws, _, _ = await self.start_socket(cipher=cipher, transport=transport, mode=mode)
                _, symbols, recovered, _ = await self.drain_transmission(ws, capture=False)
                tail_symbols, tail, result = await self.finish_reception(ws)
                self.assertEqual(symbols + tail_symbols, "")
                self.assertEqual(recovered + tail, "")
                self.assertFalse(result["matched"], result)
                self.assertFalse(result["success"], result)
                if cipher == "sealcrypt":
                    self.assertTrue(result["errors"], result)
                await ws.close()

    async def test_empty_input_is_rejected_and_empty_capture_never_matches(self):
        for mode, message in (("raw", ""), ("checked", ""), ("text", " \t\n")):
            ws = await self.client.ws_connect(f"/api/live?session={uuid.uuid4()}")
            await ws.send_json({"type": "start", "operation": "acoustic", "mode": mode, "text": message})
            error = await ws.receive_json(timeout=5)
            self.assertEqual(error["type"], "error")
            self.assertIn("nonempty", error["error"])
            await ws.close()
        ws, _, _ = await self.start_socket(text="E")
        await self.drain_transmission(ws, capture=False)
        _, recovered, result = await self.finish_reception(ws, silence=False)
        self.assertEqual(recovered, "")
        self.assertFalse(result["matched"])
        self.assertFalse(result["success"])
        await ws.close()

    async def test_different_clean_microphone_message_does_not_match(self):
        ws, _, _ = await self.start_socket(mode="text", text="SOS")
        await self.drain_transmission(ws, capture=False)
        encoder = pipeline.audio_encoder("morselink", pipeline.audio_settings(wpm=30), "text")
        recovered = ""
        for chunks in (encoder.feed("NO"), encoder.finish()):
            for pcm in chunks:
                await ws.send_bytes(pcm.astype("<f4").tobytes())
                recovered += (await ws.receive_json(timeout=5))["recovered"]
        _, tail, result = await self.finish_reception(ws)
        self.assertEqual(recovered + tail, "NO")
        self.assertEqual(result["errors"], [])
        self.assertFalse(result["matched"])
        self.assertFalse(result["success"])
        await ws.close()

    async def test_plaintext_match_requires_clean_finite_input(self):
        for cipher in pipeline.CIPHERS:
            with self.subTest(cipher=cipher):
                ws, _, ready = await self.start_socket(cipher=cipher, mode="checked", transport="audiolink")
                await self.drain_transmission(ws, capture=False)
                # Intact data frame with the cipher's required end frame deliberately missing.
                first_frame = re.findall(r"VVV\([A-Z2-7]+\)", ready["symbols"])[0]
                encoder = pipeline.audio_encoder("audiolink", pipeline.audio_settings("audiolink"), "checked")
                recovered = ""
                for chunks in (encoder.feed(first_frame), encoder.finish()):
                    for pcm in chunks:
                        await ws.send_bytes(pcm.astype("<f4").tobytes())
                        recovered += (await ws.receive_json(timeout=5))["recovered"]
                _, tail, result = await self.finish_reception(ws)
                self.assertEqual(recovered + tail, "Hi!\n")
                self.assertTrue(result["matched"], result)
                self.assertFalse(result["complete"], result)
                self.assertFalse(result["success"], result)
                self.assertTrue(any("end frame" in error for error in result["errors"]), result)
                await ws.close()

    async def test_rejects_streaming_and_finishing_before_playback_drain(self):
        ws = await self.client.ws_connect(f"/api/live?session={uuid.uuid4()}")
        await ws.send_json({"type": "start", "operation": "acoustic", "streaming": True})
        error = await ws.receive_json(timeout=5)
        self.assertEqual(error["type"], "error")
        self.assertIn("finite", error["error"])
        await ws.close()
        for begin in (False, True):
            ws, _, _ = await self.start_socket(mode="text", text="E")
            if begin:
                await ws.send_json({"type": "begin"})
                while True:
                    data = await self.receive_event(ws)
                    if isinstance(data, dict) and data["type"] == "draining":
                        break
            await ws.send_json({"type": "end"})
            error = await ws.receive_json(timeout=5)
            self.assertEqual(error["type"], "error", error)
            self.assertIn("playback has drained", error["error"])
            await ws.close()

    async def test_capture_works_while_playback_credit_is_exhausted_and_stop_releases_session(self):
        ws, session, _ = await self.start_socket(mode="text", text="SOS SOS SOS")
        await ws.send_json({"type": "begin"})
        samples = 0
        while True:
            try:
                event = await ws.receive(timeout=.1)
            except asyncio.TimeoutError:
                break
            if event.type == WSMsgType.BINARY:
                samples += len(event.data) // 4
        self.assertGreater(samples, 48000)
        self.assertLessEqual(samples, 2 * 48000)
        await ws.send_bytes(np.zeros(4800, dtype="<f4").tobytes())
        self.assertEqual((await ws.receive_json(timeout=5))["ack"], 4800)
        await ws.send_json({"type": "stop"})
        self.assertEqual((await ws.receive(timeout=5)).type, WSMsgType.CLOSE)
        self.assertNotIn(session, self.app[SESSIONS])
        ws, session, _ = await self.start_socket()
        await ws.close()
        await asyncio.sleep(.01)
        self.assertNotIn(session, self.app[SESSIONS])

    async def test_transmit_and_receive_duration_limits_are_independent(self):
        with patch("encrypted_radio.web.MAX_SECONDS", 2):
            ws, _, _ = await self.start_socket(mode="text", text="SOS")
            samples, _, recovered, _ = await self.drain_transmission(ws)
            _, tail, result = await self.finish_reception(ws, silence=False)
            self.assertGreater(2 * samples / 48000, 2)
            self.assertEqual(recovered + tail, "SOS")
            self.assertTrue(result["success"], result)
            await ws.close()
            ws, _, _ = await self.start_socket(mode="text", text="SOS")
            await self.drain_transmission(ws)
            await ws.send_bytes(np.zeros(48000, dtype="<f4").tobytes())
            error = await ws.receive_json(timeout=5)
            self.assertEqual(error["type"], "error")
            self.assertIn("Microphone recording", error["error"])
            await ws.close()

    async def test_abrupt_disconnect_releases_session_for_retry(self):
        # Abort the TCP transport without a WebSocket close handshake while TX starts.
        # Repeat to exercise the race between the producer's first send and connection loss.
        for _ in range(12):
            ws, session, _ = await self.start_socket(mode="text", text="SOS SOS SOS")
            await ws.send_json({"type": "begin"})
            ws._response.connection.transport.abort()
            async with asyncio.timeout(2):
                while session in self.app[SESSIONS]:
                    await asyncio.sleep(.01)
            await ws.close()
            retry = await self.client.ws_connect(f"/api/live?session={session}")
            await retry.send_json({"type": "start", "operation": "acoustic", "mode": "text", "text": "SOS"})
            self.assertEqual((await retry.receive_json(timeout=5))["type"], "ready")
            await retry.send_json({"type": "stop"})
            self.assertEqual((await retry.receive(timeout=5)).type, WSMsgType.CLOSE)
            self.assertNotIn(session, self.app[SESSIONS])

    async def test_duplex_rejects_invalid_microphone_samples_and_playback_ack(self):
        for invalid in (b"x", np.zeros(96001, dtype="<f4").tobytes(),
                        np.array([np.nan], dtype="<f4").tobytes()):
            ws, _, _ = await self.start_socket()
            await ws.send_bytes(invalid)
            self.assertEqual((await ws.receive_json(timeout=5))["type"], "error")
            await ws.close()
        ws, _, _ = await self.start_socket()
        await ws.send_json({"type": "ack", "samples": 1})
        error = await ws.receive_json(timeout=5)
        self.assertEqual(error["type"], "error")
        self.assertIn("Invalid playback acknowledgement", error["error"])
        await ws.close()


if __name__ == "__main__":
    unittest.main()
