"""Exercise the acoustic UI lifecycle with real JavaScript and stub devices.

These tests verify browser resource and message ordering, not physical acoustics.
"""

from pathlib import Path
import shutil
import subprocess
import unittest


HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return {promise, resolve, reject};
}
async function browser({mode = 'checked', streaming = true} = {}) {
  const elements = new Map();
  class Element {
    constructor() {
      this.value = ''; this.textContent = ''; this.children = []; this.listeners = {};
      this.classList = {add(){}, remove(){}, toggle(){}};
    }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    append(...children) { this.children.push(...children); }
    replaceChildren() { this.children = []; }
    setAttribute() {}
    removeAttribute(name) { delete this[name]; }
    load() {}
    pause() {}
  }
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  for (const [id, value] of Object.entries({mode, scenario:'clean', frequency:'700',
      wpm:'20', plaintext:'Hello', cipher:'rotorcrypt', transport:'morselink'})) {
    element(id).value = value;
  }
  element('streaming').checked = streaming;
  element('begin').hidden = true;
  element('stream-controls').hidden = true;
  const contexts = [], sockets = [], worklets = [], streams = [], requests = [];
  const control = {resumeGate:null, permissionGate:null, moduleGate:null, denyPermission:false};
  const timeline = [];
  function node(kind) {
    return {kind, connections:[], disconnected:false,
      connect(target) { this.connections.push(target); },
      disconnect() { this.disconnected = true; }};
  }
  class AudioContext {
    constructor() {
      this.sampleRate = 44100; this.currentTime = 10; this.state = 'running';
      this.destination = node('destination'); this.outputs = []; this.inputs = []; this.gains = [];
      this.audioWorklet = {addModule:async () => {
        if (control.moduleGate) await control.moduleGate.promise;
      }};
      contexts.push(this);
    }
    async resume() { if (control.resumeGate) await control.resumeGate.promise; }
    async close() { this.state = 'closed'; timeline.push('context-close'); }
    createBuffer(channels, length) {
      return {length, copyToChannel(samples) { this.samples = samples.slice(); }};
    }
    createBufferSource() {
      const source = Object.assign(node('playback'), {
        start(time) { this.started = time; },
        stop() { this.stopped = true; },
      });
      this.outputs.push(source); return source;
    }
    createMediaStreamSource(stream) {
      const source = Object.assign(node('microphone'), {stream});
      this.inputs.push(source); return source;
    }
    createGain() {
      const gain = Object.assign(node('gain'), {gain:{value:1}});
      this.gains.push(gain); return gain;
    }
  }
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 1; this.bufferedAmount = 0; this.sent = []; sockets.push(this); }
    send(data) {
      const message = typeof data === 'string' ? JSON.parse(data) : data;
      this.sent.push(message); timeline.push(message instanceof ArrayBuffer ? 'pcm' : message.type);
    }
    close() { this.readyState = 3; timeline.push('socket-close'); }
  }
  class Worklet {
    constructor(context) {
      Object.assign(this, node('capture')); this.context = context; this.messages = [];
      this.port = {onmessage:null, postMessage:message => {
        this.messages.push(message); timeline.push(message === 'flush' ? 'flush' : 'credit');
      }};
      worklets.push(this);
    }
  }
  const config = {
    machine:{alphabet:'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', rotors:{I:{}, II:{}, III:{}}},
    key:{rotors:['I','II','III'], positions:[0,0,0], rings:[0,0,0], plugboard:['AB','CD']},
  };
  const sandbox = {
    document:{getElementById:element, createElement:() => new Element()},
    window:{addEventListener(){}}, crypto:require('node:crypto').webcrypto,
    location:{host:'127.0.0.1:8765'}, AudioContext, AudioWorkletNode:Worklet,
    WebSocket:Socket, Float32Array, ArrayBuffer, Set, AbortController, console,
    setTimeout, clearTimeout,
    navigator:{mediaDevices:{getUserMedia:async options => {
      requests.push(options);
      if (control.denyPermission) {
        const error = new Error('Denied'); error.name = 'NotAllowedError'; throw error;
      }
      const track = {stopped:false, listeners:{},
        stop() { this.stopped = true; timeline.push('track-stop'); },
        addEventListener(name, callback) { this.listeners[name] = callback; },
        getSettings() { return {echoCancellation:false, noiseSuppression:false, autoGainControl:false}; },
      };
      const stream = {getTracks:() => [track], getAudioTracks:() => [track]};
      streams.push(stream);
      if (control.permissionGate) await control.permissionGate.promise;
      return stream;
    }}},
    fetch:async () => ({ok:true, json:async () => config}),
  };
  const source = fs.readFileSync(process.argv[1], 'utf8');
  const app = await vm.runInNewContext('(async()=>{' + source
    + '; return {startLive, cleanup, queuePlayback, getActive:()=>active};})()', sandbox);
  const event = (live, message) => live.ws.onmessage({data:JSON.stringify(message)});
  const capture = samples => worklets.at(-1).port.onmessage({data:samples});
  const messages = (live, type) => live.ws.sent.filter(message => message.type === type);
  async function prepare() {
    await app.startLive('acoustic');
    const live = app.getActive();
    live.ws.onopen();
    await event(live, {type:'ready', operation:'acoustic', duration:1.25, symbols:'CIPHER', streaming:false});
    return live;
  }
  async function arm(live) {
    capture(new Float32Array(128));
    await event(live, {type:'received', ack:128, symbols:'', recovered:''});
  }
  return {app, element, contexts, sockets, worklets, streams, requests, control,
    timeline, event, capture, messages, prepare, arm};
}
"""


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for acoustic frontend lifecycle tests.')
class AcousticFrontendTests(unittest.TestCase):
    def run_browser(self, checks):
        script = HARNESS + '\n(async()=>{\n' + checks + r"""
})().catch(error => { console.error(error); process.exit(1); });
"""
        result = subprocess.run(
            [shutil.which('node'), '-e', script,
             str(Path(__file__).parents[1] / 'src/encrypted_radio/static/app.js')],
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_microphone_arms_before_play_and_tail_flush_precedes_completion(self):
        self.run_browser(r"""
const h = await browser();
assert.equal(h.element('live-acoustic').disabled, false);
assert.equal(typeof h.element('live-acoustic').listeners.click, 'function');
const live = await h.prepare();
assert.equal(h.contexts.length, 1, 'Playback and capture share one audio clock');
assert.equal(h.requests.length, 1, 'One user action requests one microphone stream');
for (const setting of ['echoCancellation', 'noiseSuppression', 'autoGainControl']) {
  assert.equal(h.requests[0].audio[setting], false);
}
const start = h.messages(live, 'start')[0];
assert.equal(start.operation, 'acoustic');
assert.equal(start.sample_rate, 44100);
assert.equal(start.streaming, false, 'An acoustic comparison must finish even with streaming selected');
assert.equal(h.worklets[0].context, live.context);
assert.equal(live.context.inputs[0].stream, h.streams[0]);
assert.equal(live.context.gains[0].gain.value, 0, 'Do not monitor microphone audio through the speakers');
assert.equal(h.element('ciphertext').textContent, 'CIPHER');
assert.notEqual(h.element('duration').textContent, '—');
assert.equal(h.element('begin').hidden, true);
await h.event(live, {type:'received', ack:0});
assert.equal(h.element('begin').hidden, true, 'A zero-sample event cannot arm playback');
await h.element('begin').listeners.click();
assert.equal(h.messages(live, 'begin').length, 0, 'Play is guarded until microphone input is confirmed');
await h.arm(live);
assert.equal(h.element('begin').hidden, false);
assert.equal(h.messages(live, 'begin').length, 0, 'Capture preparation must not autoplay');
await Promise.all([h.element('begin').listeners.click(), h.element('begin').listeners.click()]);
assert.equal(h.messages(live, 'begin').length, 1);
assert.equal(h.element('stream-controls').hidden, true);

const microphone = new Float32Array([0.1, 0.2, 0.3, 0.4]);
h.capture(microphone);
assert.equal(live.pending, microphone.length);
const sentPcm = () => live.ws.sent.filter(message => message instanceof ArrayBuffer);
assert.equal(sentPcm().at(-1), microphone.buffer, 'Receiver input comes from microphone capture');
const beforePlayback = sentPcm().length;
const creditsBeforePlayback = h.worklets[0].messages.length;
const speaker = new Float32Array([0.7, 0.6, 0.5]);
await live.ws.onmessage({data:speaker.buffer});
const output = live.context.outputs[0];
assert.equal(sentPcm().length, beforePlayback, 'Transmitted PCM must never bypass the acoustic path');
assert.deepEqual(output.connections, [live.context.destination]);
assert.deepEqual(Array.from(output.buffer.samples), Array.from(speaker));
output.onended();
assert.equal(h.messages(live, 'ack').at(-1).samples, speaker.length);
assert.equal(live.pending, microphone.length, 'Playback acknowledgements cannot consume capture credits');
assert.equal(h.worklets[0].messages.length, creditsBeforePlayback);
await h.event(live, {type:'received', ack:microphone.length, symbols:'HE', recovered:'He'});
assert.equal(live.pending, 0);
assert.equal(h.worklets[0].messages.at(-1).ack, microphone.length);
assert.equal(h.messages(live, 'ack').length, 1, 'Capture credits cannot acknowledge speaker playback');

await h.event(live, {type:'transmitted', duration:1.25});
assert.equal(h.streams[0].getTracks()[0].stopped, false, 'Keep listening after the final played sample');
assert.equal(live.tailUntil, live.context.currentTime + 1);
live.context.currentTime = live.tailUntil - 0.01;
h.capture(new Float32Array(128));
assert.equal(h.worklets[0].messages.includes('flush'), false);
assert.equal(h.messages(live, 'end').length, 0);
live.context.currentTime = live.tailUntil + 0.01;
h.capture(new Float32Array(128));
assert.equal(h.worklets[0].messages.filter(message => message === 'flush').length, 1);
assert.equal(h.streams[0].getTracks()[0].stopped, true);
assert.equal(h.messages(live, 'end').length, 0, 'Wait for buffered microphone samples to flush');
const residual = new Float32Array([0.2, 0.1]);
h.capture(residual);
assert.equal(sentPcm().at(-1), residual.buffer);
h.capture({flushed:true});
assert.equal(h.messages(live, 'end').length, 1);
assert.ok(h.timeline.lastIndexOf('pcm') < h.timeline.indexOf('end'));
await h.event(live, {type:'complete', success:true, matched:true, mode:'checked',
  symbols:'LLO', recovered:'llo', duration:1.25, errors:[]});
assert.equal(h.element('received').textContent, 'HELLO');
assert.equal(h.element('recovered').textContent, 'Hello');
assert.equal(h.element('verification').textContent, 'ACOUSTIC MATCH');
assert.equal(h.app.getActive(), null);
assert.equal(live.context.state, 'closed');
assert.equal(live.ws.readyState, 3);
assert.equal(h.worklets[0].disconnected, true);
assert.equal(h.element('live-acoustic').disabled, false);
""")

    def test_match_mismatch_and_server_errors_are_distinct(self):
        self.run_browser(r"""
for (const [mode, success, matched, errors] of [
    ['text', true, true, []], ['checked', false, false, ['missing final frame']],
    ['checked', true, false, []]]) {
  const h = await browser({mode});
  const live = await h.prepare();
  await h.event(live, {type:'complete', success, matched, mode, symbols:'SOS',
    recovered:'SOS', duration:1, errors});
  const badge = h.element('verification').textContent;
  if (success && matched) assert.equal(badge, 'TEXT MATCH');
  else {
    assert.notEqual(badge, 'ACOUSTIC MATCH');
    assert.notEqual(badge, 'TEXT MATCH');
    assert.match(badge, /MISMATCH|FAILED|ERROR|DIAGNOSTICS/);
  }
  assert.equal(h.app.getActive(), null);
  assert.equal(h.streams[0].getTracks()[0].stopped, true);
  assert.equal(live.context.state, 'closed');
}
const h = await browser();
const live = await h.prepare();
await h.event(live, {type:'error', error:'Microphone sample discontinuity'});
assert.match(h.element('status').textContent, /discontinuity/);
assert.equal(h.element('verification').textContent, 'ERROR');
assert.equal(h.app.getActive(), null);
assert.equal(live.context.state, 'closed');
assert.equal(h.streams[0].getTracks()[0].stopped, true);
""")

    def test_cancellation_releases_pending_and_active_device_resources(self):
        self.run_browser(r"""
// Double clicks and Stop while the first resume is pending cannot allocate another session.
{
  const h = await browser();
  h.control.resumeGate = deferred();
  const first = h.app.startLive('acoustic');
  const second = h.app.startLive('acoustic');
  assert.equal(h.contexts.length, 1);
  assert.equal(h.element('live-acoustic').disabled, true);
  h.element('stop').listeners.click(); await tick();
  h.control.resumeGate.resolve(); await Promise.all([first, second]);
  assert.equal(h.contexts[0].state, 'closed');
  assert.equal(h.app.getActive(), null);
  assert.equal(h.requests.length, 0);
  assert.equal(h.sockets.length, 0);
}
// Permission denial reports a failure and releases the already-created context.
{
  const h = await browser(); h.control.denyPermission = true;
  await h.app.startLive('acoustic');
  assert.match(h.element('status').textContent, /denied/i);
  assert.equal(h.contexts[0].state, 'closed');
  assert.equal(h.app.getActive(), null);
  assert.equal(h.sockets.length, 0);
}
// Permission can resolve after Stop; its newly available track must still be stopped.
{
  const h = await browser(); h.control.permissionGate = deferred();
  const pending = h.app.startLive('acoustic'); await tick();
  assert.equal(h.streams.length, 1);
  h.element('stop').listeners.click(); await tick();
  h.control.permissionGate.resolve(); await pending;
  assert.equal(h.streams[0].getTracks()[0].stopped, true);
  assert.equal(h.contexts[0].state, 'closed');
  assert.equal(h.app.getActive(), null);
  assert.equal(h.sockets.length, 0);
}
// A disconnect during worklet loading must not attach a late worklet to a closed context.
{
  const h = await browser(); h.control.moduleGate = deferred();
  await h.app.startLive('acoustic');
  const live = h.app.getActive(); live.ws.onopen();
  const loading = h.event(live, {type:'ready', operation:'acoustic', duration:1, symbols:'SOS'});
  await tick(); live.ws.readyState = 3; live.ws.onclose(); await tick();
  h.control.moduleGate.resolve(); await loading;
  assert.equal(h.worklets.length, 0);
  assert.equal(h.streams[0].getTracks()[0].stopped, true);
  assert.equal(live.context.state, 'closed');
  assert.equal(h.app.getActive(), null);
}
// Stop during the Play gesture's resume cannot begin a stale session.
{
  const h = await browser(); const live = await h.prepare(); await h.arm(live);
  h.control.resumeGate = deferred();
  const playing = h.element('begin').listeners.click(); await tick();
  h.element('stop').listeners.click(); await tick();
  h.control.resumeGate.resolve(); await playing;
  assert.equal(h.messages(live, 'begin').length, 0);
  assert.equal(h.streams[0].getTracks()[0].stopped, true);
  assert.equal(live.context.state, 'closed');
  assert.equal(live.ws.readyState, 3);
  assert.equal(h.app.getActive(), null);
}
// Active playback, microphone, and their graph are all released on disconnect.
{
  const h = await browser(); const live = await h.prepare(); await h.arm(live);
  await h.element('begin').listeners.click();
  await live.ws.onmessage({data:new Float32Array(128).buffer});
  live.ws.readyState = 3; live.ws.onclose(); await tick();
  assert.equal(live.context.outputs[0].stopped, true);
  assert.equal(h.streams[0].getTracks()[0].stopped, true);
  assert.equal(h.worklets[0].disconnected, true);
  assert.equal(live.context.inputs[0].disconnected, true);
  assert.equal(live.context.gains[0].disconnected, true);
  assert.equal(live.context.state, 'closed');
  assert.equal(h.app.getActive(), null);
}
""")

    def test_tail_flush_overflow_and_ended_microphone_fail_explicitly(self):
        self.run_browser(r"""
for (const overflow of ['samples', 'socket']) {
  const h = await browser(); const live = await h.prepare(); await h.arm(live);
  await h.element('begin').listeners.click();
  await h.event(live, {type:'transmitted'});
  live.context.currentTime = live.tailUntil + 0.01;
  h.capture(new Float32Array(overflow === 'samples' ? 2 * live.context.sampleRate : 128));
  assert.equal(live.finishing, true);
  assert.equal(h.worklets[0].messages.at(-1), 'flush');
  if (overflow === 'socket') live.ws.bufferedAmount = 8 * live.context.sampleRate + 4;
  h.capture(new Float32Array(1));
  await tick();
  assert.equal(h.messages(live, 'discontinuity').length, 1,
    'Final buffered samples must still enforce capture bounds while finishing');
  assert.equal(h.messages(live, 'stop').length, 1);
  assert.equal(h.messages(live, 'end').length, 0);
  h.capture({flushed:true});
  assert.equal(h.messages(live, 'end').length, 0, 'A failed flush cannot finalize as a valid receive');
  assert.match(h.element('verification').textContent, /ERROR|FAILED/);
  assert.equal(h.streams[0].getTracks()[0].stopped, true);
  assert.equal(live.context.state, 'closed');
  assert.equal(live.ws.readyState, 3);
  assert.equal(h.app.getActive(), null);
}
for (const endedBeforeSetup of [true, false]) {
  const h = await browser(); await h.app.startLive('acoustic');
  const live = h.app.getActive(); live.ws.onopen();
  const track = h.streams[0].getTracks()[0];
  if (endedBeforeSetup) track.readyState = 'ended';
  await h.event(live, {type:'ready', operation:'acoustic', duration:1, symbols:'SOS'});
  if (!endedBeforeSetup) track.listeners.ended();
  await tick();
  assert.equal(h.messages(live, 'discontinuity').length, 1);
  assert.equal(h.messages(live, 'stop').length, 1);
  assert.equal(live.context.state, 'closed');
  assert.equal(h.app.getActive(), null);
}
""")

    def test_stale_callbacks_and_rejections_do_not_touch_replacement_session(self):
        self.run_browser(r"""
// A cancelled capture worklet and playback source can still deliver queued callbacks.
{
  const h = await browser(); const old = await h.prepare(); await h.arm(old);
  await h.element('begin').listeners.click();
  await old.ws.onmessage({data:new Float32Array(128).buffer});
  const capture = h.worklets[0].port.onmessage;
  h.element('stop').listeners.click(); await tick();
  const replacement = await h.prepare();
  const count = replacement.ws.sent.length;
  const status = h.element('status').textContent;
  capture({data:new Float32Array(128)});
  capture({data:{flushed:true}});
  capture({data:{discontinuity:'stale discontinuity'}});
  old.context.outputs[0].onended();
  h.streams[0].getTracks()[0].listeners.ended();
  old.ws.onclose(); old.ws.onerror();
  await h.event(old, {type:'error', error:'stale connection error'});
  assert.equal(replacement.ws.sent.length, count);
  assert.equal(h.element('status').textContent, status);
  assert.equal(h.app.getActive(), replacement);
  assert.equal(h.streams[1].getTracks()[0].stopped, false);
  await h.app.cleanup(replacement);
}
// Rejections from cancelled asynchronous browser operations belong to the old session.
for (const pendingOperation of ['resume', 'module']) {
  const h = await browser();
  let old, pending;
  const gate = deferred();
  if (pendingOperation === 'resume') {
    old = await h.prepare(); await h.arm(old);
    h.control.resumeGate = gate;
    pending = h.element('begin').listeners.click();
  } else {
    h.control.moduleGate = gate;
    await h.app.startLive('acoustic'); old = h.app.getActive(); old.ws.onopen();
    pending = h.event(old, {type:'ready', operation:'acoustic', duration:1, symbols:'SOS'});
  }
  await tick(); h.element('stop').listeners.click(); await tick();
  h.control.resumeGate = null; h.control.moduleGate = null;
  await h.app.startLive('tx');
  const replacement = h.app.getActive(); replacement.ws.onopen();
  const status = h.element('status').textContent;
  const badge = h.element('verification').textContent;
  const count = replacement.ws.sent.length;
  gate.reject(new Error('Old browser operation failed'));
  await pending;
  assert.equal(h.app.getActive(), replacement);
  assert.equal(replacement.context.state, 'running');
  assert.equal(replacement.ws.sent.length, count);
  assert.equal(h.element('status').textContent, status);
  assert.equal(h.element('verification').textContent, badge);
  await h.app.cleanup(replacement);
}
""")


if __name__ == '__main__':
    unittest.main()
