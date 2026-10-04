"""Browser API acceptance tests use the actual cipher and audio implementations."""
import asyncio
import io
import json
import threading
import shutil
import subprocess
from pathlib import Path
import unittest
import uuid
import wave
from unittest.mock import patch

import numpy as np
from aiohttp import FormData, WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from encrypted_radio.audio import AudioSettings, MorseEncoder
from encrypted_radio.web import JOBS, SESSIONS, TEMP_ROOT, WORKERS, create_app, serve


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app()
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        root = self.app[TEMP_ROOT]
        await self.client.close()
        self.assertFalse(root.exists(), 'Shutdown must remove session artifacts.')

    async def start_socket(self, **options):
        session = str(uuid.uuid4())
        ws = await self.client.ws_connect(f'/api/live?session={session}')
        await ws.send_json({'type': 'start', 'operation': 'rx', 'mode': 'text', 'rx_frequency': 700, 'rx_wpm': 20, **options})
        ready = await ws.receive_json(timeout=5)
        self.assertEqual(ready['type'], 'ready', ready)
        return ws, session

    async def test_disconnect_cancels_worker_before_removing_artifacts(self):
        entered = threading.Event()
        cancelled = threading.Event()

        def wait_for_cancellation(text, *, output_dir, cancel_event, **kwargs):
            (output_dir / 'partial.wav').write_bytes(b'partial')
            entered.set()
            if not cancel_event.wait(5):
                raise RuntimeError('Worker was not cancelled.')
            self.assertTrue((output_dir / 'partial.wav').exists())
            cancelled.set()
            raise InterruptedError('Cancelled.')

        with patch('encrypted_radio.demo.run_roundtrip', side_effect=wait_for_cancellation):
            request = asyncio.create_task(self.client.post('/api/roundtrip', json={'text': 'Hello'}))
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            second = await self.client.post('/api/roundtrip', json={'text': 'Concurrent'})
            self.assertEqual(second.status, 409)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            self.assertTrue(await asyncio.to_thread(cancelled.wait, 2))
            for _ in range(100):
                if not self.app[WORKERS]:
                    break
                await asyncio.sleep(.01)
            self.assertEqual(len(self.app[WORKERS]), 0)
            self.assertEqual(len(self.app[JOBS]), 0)
            self.assertEqual(list(self.app[TEMP_ROOT].iterdir()), [])

    async def test_json_settings_limit_and_bad_live_handshake(self):
        response = await self.client.post('/api/roundtrip', data='x' * 70000,
                                          headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status, 400)
        response = await self.client.get(f'/api/live?session={uuid.uuid4()}')
        self.assertEqual(response.status, 400)
        self.assertEqual(len(self.app[SESSIONS]), 0)
        ws = await self.client.ws_connect(f'/api/live?session={uuid.uuid4()}')
        await ws.send_json([])
        self.assertEqual((await ws.receive_json(timeout=5))['type'], 'error')
        await ws.close()

    async def test_configuration_and_local_assets(self):
        response = await self.client.get('/api/config')
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertEqual(len(result['machine']['alphabet']), 49)
        self.assertEqual(len(result['key']['plugboard']), 12)
        for url in ('/', '/static/app.js', '/static/styles.css', '/static/capture-worklet.js'):
            asset = await self.client.get(url)
            self.assertEqual(asset.status, 200)
            self.assertIn("frame-ancestors 'none'", asset.headers['Content-Security-Policy'])
        self.assertEqual((await self.client.get('/static/')).status, 403)
        html = await (await self.client.get('/')).text()
        for identifier in ('run', 'live-tx', 'live-rx'):
            import re
            tag = re.search(r'<button\b[^>]*id="' + identifier + r'"[^>]*>', html).group()
            self.assertIn('disabled', tag, 'Actions must stay disabled before configuration loads.')

    async def test_host_origin_and_path_restrictions(self):
        for headers in ({'Host': 'evil.example'}, {'Origin': 'https://evil.example'}, {'Origin': 'null'}, {'Host': '127.0.0.1:evil'}):
            response = await self.client.get('/api/config', headers=headers)
            self.assertEqual(response.status, 403, headers)
        self.assertEqual((await self.client.get('/api/artifacts/unknown/machine.json')).status, 404)
        with self.assertRaises(ValueError):
            serve(host='0.0.0.0')

    async def test_real_roundtrip_and_download(self):
        response = await self.client.post('/api/roundtrip', json={'text': 'Hi!\n', 'mode': 'checked'})
        result = await response.json()
        self.assertEqual(response.status, 200, result)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['recovered'], 'Hi!\n')
        self.assertEqual(result['received_symbols'], result['ciphertext'])
        wav_response = await self.client.get(result['wav_url'])
        self.assertEqual(wav_response.status, 200)
        with wave.open(io.BytesIO(await wav_response.read()), 'rb') as source:
            self.assertEqual(source.getframerate(), 48000)
            self.assertAlmostEqual(source.getnframes() / source.getframerate(), result['duration'])

    async def test_invalid_input_and_preflight_limits(self):
        for settings in ({'text': 'é'}, {'text': 'a' * 513}, {'text': 'HI', 'mode': 'invalid'}, {'text': 'HI', 'sample_rate': 32000}, {'text': 'HI', 'frequency': 100}, {'text': 'HI', 'rx_wpm': 50}, {'text': '[', 'mode': 'text'}, {'text': 'HI', 'mode': 'raw', 'scenario': 'lost-block'}, {'text': '\x00' * 512, 'wpm': 8}):
            response = await self.client.post('/api/roundtrip', json=settings)
            self.assertEqual(response.status, 400, settings)
        self.assertEqual(len(self.app[JOBS]), 0)

    async def test_wav_upload_uses_real_decoder_at_both_sample_rates(self):
        for rate in (44100, 48000):
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
                encoder = MorseEncoder(AudioSettings(sample_rate=rate), profile='text')
                for pcm in (*encoder.feed('SOS'), *encoder.finish()):
                    output.writeframesraw((pcm * 32767).astype('<i2').tobytes())
            form = FormData()
            form.add_field('settings', json.dumps({'mode': 'text', 'rx_frequency': 700, 'rx_wpm': 20}))
            form.add_field('audio', buffer.getvalue(), filename='capture.wav', content_type='audio/wav')
            response = await self.client.post('/api/decode', data=form)
            result = await response.json()
            self.assertEqual(response.status, 200, result)
            self.assertEqual(result['recovered'], 'SOS')
            self.assertIsNone(result['matched'])

    async def test_upload_bound_is_checked_while_reading(self):
        form = FormData()
        form.add_field('audio', b'x' * 100, filename='large.wav')
        with patch('encrypted_radio.web.MAX_UPLOAD', 32):
            response = await self.client.post('/api/decode', data=form)
        self.assertEqual(response.status, 413)
        self.assertEqual(len(self.app[JOBS]), 0)
        self.assertEqual(list(self.app[TEMP_ROOT].iterdir()), [])

    async def test_live_reception_ack_and_finish_at_both_sample_rates(self):
        for rate in (44100, 48000):
            ws, session = await self.start_socket(sample_rate=rate)
            encoder = MorseEncoder(AudioSettings(sample_rate=rate), profile='text')
            symbols, recovered = '', ''
            for pcm in (*encoder.feed('SOS'), *encoder.finish()):
                await ws.send_bytes(pcm.astype('<f4').tobytes())
                event = await ws.receive_json(timeout=5)
                self.assertEqual(event['ack'], len(pcm))
                symbols += event['symbols']; recovered += event['recovered']
            await ws.send_json({'type': 'end'})
            event = await ws.receive_json(timeout=5)
            self.assertEqual(event['type'], 'complete')
            symbols += event['symbols']; recovered += event['recovered']
            self.assertEqual(symbols, 'SOS')
            self.assertEqual(recovered, 'SOS')
            await ws.close()
            self.assertNotIn(session, self.app[SESSIONS])

    async def test_live_session_exclusion_stop_and_disconnect(self):
        ws, session = await self.start_socket()
        response = await self.client.get(f'/api/live?session={session}')
        self.assertEqual(response.status, 409)
        await ws.send_json({'type': 'stop'})
        self.assertEqual((await ws.receive(timeout=5)).type, WSMsgType.CLOSE)
        self.assertNotIn(session, self.app[SESSIONS])
        ws2, session2 = await self.start_socket()
        await ws2.close()
        # Close-handshake completion schedules cleanup on the server loop.
        await asyncio.sleep(.01)
        self.assertNotIn(session2, self.app[SESSIONS])

    async def test_live_rejects_sample_loss_and_invalid_pcm(self):
        ws, _ = await self.start_socket(mode='raw')
        await ws.send_json({'type': 'discontinuity'})
        self.assertEqual((await ws.receive_json(timeout=5))['type'], 'error')
        await ws.close()
        for pcm in (np.zeros(96001, dtype='<f4'), np.array([np.nan], dtype='<f4')):
            ws, _ = await self.start_socket()
            await ws.send_bytes(pcm.tobytes())
            self.assertEqual((await ws.receive_json(timeout=5))['type'], 'error')
            await ws.close()

    async def test_tx_waits_for_begin_and_acknowledges_exact_audio(self):
        ws, _ = await self.start_socket(operation='tx', text='SOS', mode='text')
        # Server must not start producing playable audio during preflight.
        with self.assertRaises(asyncio.TimeoutError):
            await ws.receive(timeout=.05)
        await ws.send_json({'type': 'begin'})
        samples = 0
        while True:
            event = await ws.receive(timeout=5)
            if event.type == WSMsgType.BINARY:
                self.assertLessEqual(len(event.data) // 4, 960)
                count = len(event.data) // 4; samples += count
                await ws.send_json({'type': 'ack', 'samples': count})
            elif event.type == WSMsgType.TEXT:
                data = json.loads(event.data)
                if data['type'] == 'complete':
                    self.assertTrue(data['success'])
                    self.assertAlmostEqual(data['duration'], samples / 48000)
                    break
                self.assertNotEqual(data['type'], 'error', data)
            else:
                self.fail(f'Unexpected websocket message: {event}')
        await ws.close()

    async def test_tx_bounds_unacknowledged_pcm_and_cancel(self):
        ws, session = await self.start_socket(operation='tx', text='SOS SOS SOS', mode='text')
        await ws.send_json({'type': 'begin'})
        received = 0
        while True:
            try:
                event = await ws.receive(timeout=.1)
            except asyncio.TimeoutError:
                break
            if event.type == WSMsgType.BINARY:
                received += len(event.data) // 4
        self.assertLessEqual(received, 2 * 48000)
        self.assertGreater(received, 48000)
        await ws.send_json({'type': 'stop'})
        self.assertEqual((await ws.receive(timeout=5)).type, WSMsgType.CLOSE)
        self.assertNotIn(session, self.app[SESSIONS])

    async def test_tx_streaming_and_bad_ack(self):
        ws, _ = await self.start_socket(operation='tx', text='', mode='text', streaming=True)
        await ws.send_json({'type': 'begin'})
        await ws.send_json({'type': 'text', 'text': 'S'})
        await ws.send_json({'type': 'end'})
        symbols = ''
        while True:
            event = await ws.receive(timeout=5)
            if event.type == WSMsgType.BINARY:
                await ws.send_json({'type': 'ack', 'samples': len(event.data) // 4})
            else:
                data = json.loads(event.data)
                if data['type'] == 'symbols': symbols += data['symbols']
                if data['type'] == 'complete': break
                self.assertNotEqual(data['type'], 'error', data)
        self.assertEqual(symbols, 'S')
        await ws.close()
        ws, _ = await self.start_socket(operation='tx', text='SOS', mode='text')
        await ws.send_json({'type': 'ack', 'samples': 1})
        self.assertEqual((await ws.receive_json(timeout=5))['type'], 'error')
        await ws.close()


class BrowserLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for the frontend lifecycle smoke test.')
    def test_audio_lifecycle_with_browser_api_stubs(self):
        # Real frontend code; only browser device/DOM/network surfaces are replaced.
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
class Element {
  constructor() { this.value = ''; this.textContent = ''; this.children = []; this.listeners = {}; this.classList = {add(){}, remove(){}, toggle(){}}; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  setAttribute() {}
  removeAttribute(name) { delete this[name]; }
  load() {}
  pause() {}
}
const element = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
for (const [id, value] of Object.entries({mode:'checked', scenario:'clean', frequency:'700', wpm:'20', plaintext:'Hello'})) element(id).value = value;
const contexts = [], sockets = [], worklets = [], streams = [], starts = [];
let holdResume = false, releaseResume, failResume = false, denyMicrophone = false;
class AudioContext {
  constructor() { this.sampleRate = 44100; this.currentTime = 1; this.state = 'running'; this.destination = {}; this.audioWorklet = {addModule:async()=>{}}; contexts.push(this); }
  async resume() { if (failResume) throw new Error('Resume failed'); if (holdResume) await new Promise(resolve => { releaseResume = resolve; }); }
  async close() { this.state = 'closed'; }
  createBuffer() { return {copyToChannel(){}}; }
  createBufferSource() { return {connect(){}, disconnect(){}, start(time){starts.push(time);}, stop(){}}; }
  createMediaStreamSource() { return {connect(){}, disconnect(){}}; }
  createGain() { return {gain:{value:1}, connect(){}, disconnect(){}}; }
}
class Socket {
  static OPEN = 1;
  constructor() { this.readyState = 1; this.bufferedAmount = 0; this.sent = []; sockets.push(this); }
  send(data) { this.sent.push(typeof data === 'string' ? JSON.parse(data) : data); }
  close() { this.readyState = 3; }
}
class Worklet {
  constructor() { this.port = {postMessage(){}, onmessage:null}; worklets.push(this); }
  connect() {}
  disconnect() { this.disconnected = true; }
}
const config = {machine:{alphabet:'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,:?\'/-()"=+@', rotors:{I:{},II:{},III:{}}},key:{rotors:['I','II','III'], positions:[0,0,0], rings:[0,0,0], plugboard:['AB','CD','EF','GH','IJ','KL','MN','OP','QR','ST','UV','WX']}};
const sandbox = {
  document:{getElementById:element, createElement:()=>new Element()}, window:{addEventListener(){}},
  crypto:require('node:crypto').webcrypto, location:{host:'127.0.0.1:8765'},
  AudioContext, AudioWorkletNode:Worklet, WebSocket:Socket, Float32Array, ArrayBuffer, Set,
  AbortController, console,
  navigator:{mediaDevices:{getUserMedia:async()=>{
    if (denyMicrophone) { const error = new Error('Denied'); error.name = 'NotAllowedError'; throw error; }
    const track = {stopped:false, stop(){this.stopped = true;}, addEventListener(){}};
    const stream = {getTracks:()=>[track], getAudioTracks:()=>[track]}; streams.push(stream); return stream;
  }}},
  fetch:async()=>({ok:true,json:async()=>config}),
};
(async()=>{
  const source = fs.readFileSync(process.argv[1], 'utf8');
  const app = await vm.runInNewContext('(async()=>{' + source + '; return {startLive, cleanup, queuePlayback, getActive:()=>active};})()', sandbox);
  assert.equal(element('run').disabled, false); assert.equal(element('live-tx').disabled, false);
  element('playback').src = '/old-offline.wav'; element('download').href = '/old-offline.wav';
  holdResume = true;
  const first = app.startLive('tx'); const second = app.startLive('tx');
  assert.equal(contexts.length, 1, 'Double click must not create two audio contexts');
  assert.equal(element('run').disabled, true); assert.equal(element('stop').disabled, false);
  releaseResume(); await Promise.all([first, second]); holdResume = false;
  assert.equal(element('playback').src, undefined); assert.equal(element('download').href, undefined);
  const live = app.getActive(); live.ws.onopen();
  assert.equal(live.ws.sent[0].sample_rate, 44100, 'Use actual browser AudioContext rate');
  live.hasPlayed = true; live.nextTime = 1.05;
  app.queuePlayback(live, new Float32Array(882).buffer);
  assert.equal(starts[0], 1.05, 'Do not insert silent 100 ms gaps into an active waveform');
  element('stop').listeners.click(); await new Promise(resolve=>setImmediate(resolve));
  assert.equal(contexts[0].state, 'closed'); assert.equal(app.getActive(), null);
  failResume = true; await app.startLive('tx'); failResume = false;
  assert.equal(contexts.at(-1).state, 'closed', 'Failed resume must release its context');
  assert.equal(app.getActive(), null);
  denyMicrophone = true; await app.startLive('rx'); denyMicrophone = false;
  assert.match(element('status').textContent, /Microphone access was denied/);
  assert.equal(contexts.at(-1).state, 'closed'); assert.equal(app.getActive(), null);
  await app.startLive('rx');
  const receiver = app.getActive(); receiver.ws.onopen();
  await receiver.ws.onmessage({data:JSON.stringify({type:'ready',operation:'rx'})});
  worklets.at(-1).port.onmessage({data:new Float32Array(2048)});
  assert.equal(receiver.pending, 2048);
  assert.ok(receiver.ws.sent.at(-1) instanceof ArrayBuffer, 'Capture sends real PCM bytes');
  await receiver.ws.onmessage({data:JSON.stringify({type:'received',ack:2048,symbols:'SOS',recovered:'SOS'})});
  assert.equal(receiver.pending, 0); assert.equal(element('received').textContent, 'SOS');
  await app.cleanup(receiver);
  assert.ok(streams.at(-1).getTracks()[0].stopped); assert.ok(worklets.at(-1).disconnected);
  assert.equal(contexts.at(-1).state, 'closed'); assert.equal(app.getActive(), null);
  let Processor;
  const posted = [];
  vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {
    AudioWorkletProcessor:class { constructor() { this.port = {postMessage(data){posted.push(data);}}; } },
    sampleRate:44100, Float32Array, Number,
    registerProcessor(name, implementation) { Processor = implementation; },
  });
  const capture = new Processor();
  let running = true;
  for (let i = 0; i < 1000 && running; i++) running = capture.process([[new Float32Array(128)]]);
  assert.equal(running, false, 'Worklet must stop when unacknowledged audio reaches two seconds');
  assert.ok(posted.filter(item=>item instanceof Float32Array).reduce((sum,item)=>sum+item.length,0) <= 2*44100);
  assert.equal(posted.filter(item=>item.discontinuity).length, 1, 'Report the discontinuity exactly once');
  const credited = new Processor();
  for (let i = 0; i < 1000; i++) {
    assert.equal(credited.process([[new Float32Array(128)]]), true);
    if (credited.pending) credited.port.onmessage({data:{ack:credited.pending}});
  }
  console.log('Frontend lifecycle smoke test passed');
})().catch(error=>{console.error(error);process.exit(1);});
"""
        result = subprocess.run([shutil.which('node'), '-e', script,
                                 str(Path(__file__).parents[1] / 'src/encrypted_radio/static/app.js'),
                                 str(Path(__file__).parents[1] / 'src/encrypted_radio/static/capture-worklet.js')],
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
