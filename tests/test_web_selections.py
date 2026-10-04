"""Browser selection and key lifecycle tests using real JS and mocked browser I/O."""

from pathlib import Path
import shutil
import subprocess
import unittest


class BrowserSelectionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for frontend tests.')
    def test_cipher_transport_keys_and_streaming_idle(self):
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
class Element {
  constructor() {
    this.value = ''; this.textContent = ''; this.children = []; this.listeners = {};
    this.classList = {add(){}, remove(){}, toggle(){}};
  }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
  pause() {}
  load() {}
}
const element = id => {
  if (!elements.has(id)) elements.set(id, new Element());
  return elements.get(id);
};
for (const [id, value] of Object.entries({
  cipher:'rotorcrypt', transport:'morselink', mode:'checked', scenario:'clean',
  'text-encoding':'lowercase-first',
  frequency:'700', wpm:'20', plaintext:'Hello, radio!\n',
})) element(id).value = value;
// Public synthetic keys; never suitable for private messages.
const initialSeal = {version:1, algorithm:'chacha20-poly1305', key_hex:'10'.repeat(32)};
const nextSeal = {...initialSeal, key_hex:'20'.repeat(32)};
const config = {
  machine:{alphabet:'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,:?\'/-()"=+@', rotors:{I:{},II:{},III:{}}},
  key:{rotors:['I','II','III'], positions:[0,0,0], rings:[0,0,0], plugboard:['AB','CD','EF','GH','IJ','KL','MN','OP','QR','ST','UV','WX']},
  seal_key:initialSeal,
};
const requests = [];
const sandbox = {
  document:{getElementById:element, createElement:()=>new Element()},
  window:{addEventListener(){}}, crypto:require('node:crypto').webcrypto,
  location:{host:'127.0.0.1:8765'}, AbortController, Float32Array, Set, console, WebSocket:{OPEN:1},
  fetch:async(url, init) => {
    if (url === '/api/config') return {ok:true,json:async()=>config};
    const body = JSON.parse(init.body); requests.push({url,body});
    if (url === '/api/seal-key') return {ok:true,json:async()=>({seal_key:nextSeal})};
    assert.equal(url, '/api/roundtrip');
    // This test verifies presentation/request wiring, not DSP correctness.
    return {ok:true,json:async()=>({
      ciphertext:'CIPHERTEXT', received_symbols:'CIPHERTEXT', recovered:body.text,
      duration:1.25, wav_url:'/api/artifacts/example/audio.wav', errors:[],
      success:true, mode:body.mode, scenario:body.scenario, transport:body.transport,
    })};
  },
};
for (const name of ['localStorage', 'sessionStorage']) {
  Object.defineProperty(sandbox, name, {get(){throw new Error('Keys must not use persistent browser storage');}});
}
(async()=>{
  const source = fs.readFileSync(process.argv[1], 'utf8');
  const app = await vm.runInNewContext('(async()=>{' + source + '; return {options, presentation, queuePlayback};})()', sandbox);
  assert.equal(element('seal-key').type, 'password');
  assert.equal(element('seal-key').value, initialSeal.key_hex);
  assert.equal(app.options().text_encoding, 'lowercase-first');
  element('text-encoding').value = '';
  assert.equal(app.options().text_encoding, 'lowercase-first');
  element('text-encoding').value = 'lowercase-first';
  for (const cipher of ['rotorcrypt','sealcrypt']) {
    for (const transport of ['morselink','audiolink']) {
      element('cipher').value = cipher; element('transport').value = transport;
      app.presentation();
      assert.equal(element('rotor-config').hidden, cipher === 'sealcrypt');
      assert.equal(element('seal-config').hidden, cipher !== 'sealcrypt');
      assert.equal(element('morse-settings').hidden, transport === 'audiolink');
      assert.equal(element('afsk-settings').hidden, transport !== 'audiolink');
      assert.equal(element('text-encoding').disabled, false);
      if (cipher === 'sealcrypt') assert.match(element('encoding-note').textContent, /does not reduce its size/);
      else assert.match(element('encoding-note').textContent, /shortens lowercase-heavy rotor messages/);
      for (const encoding of ['lowercase-first', 'uppercase-first']) {
        element('text-encoding').value = encoding;
        await element('run').listeners.click();
        const request = requests.at(-1).body;
        assert.equal(request.cipher, cipher); assert.equal(request.transport, transport);
        assert.equal(request.text_encoding, encoding);
        assert.equal(request.text, 'Hello, radio!\n');
        if (cipher === 'sealcrypt') assert.equal(request.key.key_hex, initialSeal.key_hex);
        else assert.deepEqual(request.key.rotors, ['I','II','III']);
        assert.equal('frequency' in request, transport === 'morselink');
        assert.equal('rx_wpm' in request, transport === 'morselink');
        assert.equal(element('download').download, `${transport}.wav`);
        assert.equal(element('configuration').disabled, false);
      }
    }
  }
  element('mode').value = 'raw'; app.presentation();
  assert.match(element('mode-note').textContent, /authenticated records/);
  element('mode').value = 'text'; app.presentation();
  assert.equal(element('cipher').disabled, true);
  assert.equal(element('text-encoding').disabled, true);
  assert.equal(element('text-encoding').value, 'uppercase-first');
  assert.equal(app.options().text_encoding, 'uppercase-first');
  assert.equal(element('rotor-config').hidden, true);
  assert.equal(element('seal-config').hidden, true);
  assert.match(element('cipher-note').textContent, /bypasses encryption/);
  element('mode').value = 'checked'; app.presentation();
  assert.equal(element('text-encoding').disabled, false);
  assert.equal(app.options().text_encoding, 'uppercase-first');
  element('text-encoding').value = 'lowercase-first';
  element('mode').value = 'text'; app.presentation();
  assert.equal(app.options().text_encoding, 'uppercase-first');
  element('mode').value = 'checked'; app.presentation();
  assert.equal(app.options().text_encoding, 'lowercase-first');
  element('reveal-key').listeners.click(); assert.equal(element('seal-key').type, 'text');
  element('reveal-key').listeners.click(); assert.equal(element('seal-key').type, 'password');
  await element('generate-key').listeners.click();
  assert.equal(requests.at(-1).url, '/api/seal-key');
  assert.equal(element('seal-key').value, nextSeal.key_hex);
  assert.equal(element('seal-key').type, 'password');
  assert.equal(app.options().key.key_hex, nextSeal.key_hex);
  const imported = {...initialSeal, key_hex:'30'.repeat(32)};
  await element('seal-key-file').listeners.change({target:{
    files:[{size:150,text:async()=>JSON.stringify(imported)}], value:'key.json',
  }});
  assert.equal(app.options().key.key_hex, imported.key_hex);
  await element('seal-key-file').listeners.change({target:{
    files:[{size:100,text:async()=>'{"private fragment":"sensitive-key-fragment"'}], value:'bad.json',
  }});
  assert.equal(element('status').textContent, 'Invalid configuration JSON.');
  assert.ok(!element('status').textContent.includes('sensitive-key-fragment'));
  element('seal-key').value = 'invalid';
  assert.throws(()=>app.options(), /64-digit hexadecimal/);
  element('seal-key').value = imported.key_hex;
  const starts = [];
  const live = {
    context:{currentTime:10,sampleRate:48000,state:'running',destination:{},
      createBuffer:()=>({copyToChannel(){}}),
      createBufferSource:()=>({connect(){},disconnect(){},start(time){starts.push(time);},stop(){}}),
      async close(){this.state='closed';},
    },
    nextTime:2, hasPlayed:true, idleAllowed:true, playing:new Set(), cleaning:false,
  };
  app.queuePlayback(live, new Float32Array(960).buffer);
  assert.equal(starts[0], 10.1, 'Intentional streaming pause may restart playback');
  assert.equal(live.idleAllowed, false, 'Permission to idle is consumed by the first PCM chunk');
  live.context.currentTime = 20;
  app.queuePlayback(live, new Float32Array(960).buffer);
  assert.match(element('status').textContent, /Playback underrun/);
  assert.equal(live.cleaning, true, 'Unexpected gaps inside a batch remain fatal');
  console.log('Frontend selection, key lifecycle, and streaming pause tests passed');
})().catch(error=>{console.error(error);process.exit(1);});
"""
        result = subprocess.run(
            [shutil.which('node'), '-e', script,
             str(Path(__file__).parents[1] / 'src/encrypted_radio/static/app.js')],
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
