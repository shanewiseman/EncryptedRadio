const $ = (id) => document.getElementById(id);
const session = crypto.randomUUID();
let machine;
let key;
let active = null;
let busy = false;
let offlineController = null;

function status(message, error = false) {
  $('status').textContent = message;
  $('status').classList.toggle('error', error);
}
function badge(text) { $('verification').textContent = text; }
function duration(seconds) {
  if (!Number.isFinite(seconds)) return '—';
  const minutes = Math.floor(seconds / 60);
  return `${minutes ? `${minutes}m ` : ''}${(seconds % 60).toFixed(1)}s`;
}
function controls() {
  const locked = busy || !!active;
  for (const id of ['run', 'live-tx', 'live-rx']) $(id).disabled = locked || !machine;
  $('stop').disabled = !active && !busy;
  $('finish-rx').disabled = active?.operation !== 'rx';
}
function renderRotors() {
  $('rotors').replaceChildren();
  key.rotors.forEach((name, index) => {
    const row = document.createElement('div'); row.className = 'rotor-row';
    const fields = [
      ['Rotor', 'select', name, (value) => { key.rotors[index] = value; }],
      ['Position', 'number', key.positions[index], (value) => { key.positions[index] = Number(value); }],
      ['Ring', 'number', key.rings[index], (value) => { key.rings[index] = Number(value); }],
    ];
    for (const [labelText, type, value, update] of fields) {
      const label = document.createElement('label'); label.textContent = labelText;
      const input = document.createElement(type === 'select' ? 'select' : 'input');
      if (type === 'select') {
        Object.keys(machine.rotors).forEach((rotor) => {
          const option = document.createElement('option'); option.value = rotor; option.textContent = rotor; input.append(option);
        });
      } else { input.type = type; input.min = 0; input.max = machine.alphabet.length - 1; input.step = 1; }
      input.value = value;
      input.addEventListener('change', () => { update(input.value); rotorSummary(); });
      input.setAttribute('aria-label', `${labelText} ${index + 1}`);
      label.append(input); row.append(label);
    }
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.title = `Remove rotor ${index + 1}`;
    remove.setAttribute('aria-label', remove.title); remove.disabled = key.rotors.length <= 3;
    remove.addEventListener('click', () => { for (const field of ['rotors', 'positions', 'rings']) key[field].splice(index, 1); renderRotors(); });
    row.append(remove); $('rotors').append(row);
  });
  $('plugboard').value = key.plugboard.join(' ');
  $('add-rotor').disabled = key.rotors.length >= 8 || key.rotors.length >= Object.keys(machine.rotors).length;
  rotorSummary();
}
function rotorSummary() { $('rotor-summary').textContent = `${key.rotors.join(' · ')} / ${key.plugboard.length} cables`; }
function options() {
  if (!machine || !key) throw new Error('Configuration is still loading.');
  key.plugboard = $('plugboard').value.trim().split(/\s+/).filter(Boolean);
  const number = (id) => $(id).value === '' ? null : Number($(id).value);
  return {
    machine, key, mode: $('mode').value, scenario: $('scenario').value,
    frequency: number('frequency'), wpm: number('wpm'),
    rx_frequency: number('rx-frequency'), rx_wpm: number('rx-wpm'),
  };
}
function clearStages() {
  for (const id of ['ciphertext', 'received', 'recovered']) $(id).textContent = '';
  $('diagnostics-wrap').hidden = true;
}
function diagnostics(errors) {
  $('diagnostics-wrap').hidden = !errors?.length;
  $('diagnostics').textContent = (errors || []).join('\n');
}
async function api(url, init) {
  const response = await fetch(url, init);
  let result;
  try { result = await response.json(); } catch { throw new Error(`Request failed (${response.status}).`); }
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
  return result;
}
function showResult(result) {
  $('ciphertext').textContent = result.ciphertext;
  $('received').textContent = result.received_symbols;
  $('recovered').textContent = result.recovered;
  $('duration').textContent = duration(result.duration);
  $('channel-tag').textContent = 'OFFLINE';
  $('playback').src = result.wav_url;
  $('download').href = result.wav_url;
  $('download').classList.remove('disabled'); $('download').setAttribute('aria-disabled', 'false');
  $('audio-note').textContent = 'Actual generated audio. Playback runs at real transmission speed.';
  diagnostics(result.errors);
  if (result.scenario === 'upload') {
    badge(result.success ? 'DECODED' : 'CHECK DIAGNOSTICS');
    status(result.success ? 'WAV decoded. No original message was supplied for comparison.' : 'WAV decoded with errors. Review diagnostics and recovered output.', !result.success);
  } else if (result.scenario === 'lost-block' && result.success) {
    badge('RECOVERY VERIFIED');
    status('Offline recovery verified: a PCM segment was removed, the missing block was reported, and later blocks recovered. Missing text remains missing.');
  } else {
    badge(result.success ? (result.mode === 'text' ? 'TEXT VERIFIED' : 'EXACT MATCH') : 'MISMATCH');
    status(result.success ? (result.mode === 'text' ? 'Offline verification passed: decoded Morse matches the uppercase message with normalized spaces.' : 'Offline verification passed: recovered bytes match the original message after real audio decoding.') : 'Offline verification failed. Review the decoder diagnostics.', !result.success);
  }
}
$('run').addEventListener('click', async () => {
  if (busy || active) return;
  busy = true; offlineController = new AbortController(); controls(); clearStages(); badge('PROCESSING');
  status('Encrypting, rendering the waveform, decoding the audio, and checking the recovered bytes…');
  try {
    const result = await api('/api/roundtrip', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...options(), text: $('plaintext').value}), signal: offlineController.signal});
    showResult(result);
  } catch (error) {
    if (error.name === 'AbortError') { status('Offline operation stopped. Partial artifacts are removed.'); badge('STOPPED'); }
    else { status(error.message, true); badge('ERROR'); }
  }
  finally { busy = false; offlineController = null; controls(); }
});
$('wav-file').addEventListener('change', async ({target}) => {
  if (!target.files.length) return;
  if (busy || active) { target.value = ''; status('Stop the current operation before uploading audio.', true); return; }
  busy = true; offlineController = new AbortController(); controls(); clearStages();
  try {
    const file = target.files[0];
    if (file.size > 64 * 1024 * 1024) throw new Error('WAV uploads are limited to 64 MiB.');
    const form = new FormData(); form.append('settings', JSON.stringify(options())); form.append('audio', file);
    status('Decoding the uploaded waveform…'); badge('DECODING');
    showResult(await api('/api/decode', {method: 'POST', body: form, signal: offlineController.signal}));
  } catch (error) {
    if (error.name === 'AbortError') { status('Offline operation stopped. Partial artifacts are removed.'); badge('STOPPED'); }
    else { status(error.message, true); badge('ERROR'); }
  }
  finally { busy = false; offlineController = null; controls(); target.value = ''; }
});
for (const [id, kind] of [['machine-file', 'machine'], ['key-file', 'key']]) {
  $(id).addEventListener('change', async ({target}) => {
    try {
      if (!target.files.length) return;
      if (target.files[0].size > 65536) throw new Error('Configuration JSON is limited to 64 KiB.');
      const data = JSON.parse(await target.files[0].text());
      if (kind === 'machine') {
        if (typeof data.alphabet !== 'string' || !data.rotors || !Object.keys(data.rotors).length) throw new Error('Machine JSON needs an alphabet and rotor catalog.');
        machine = data;
      } else {
        if (!Array.isArray(data.rotors) || !Array.isArray(data.positions) || !Array.isArray(data.rings) || !Array.isArray(data.plugboard)) throw new Error('Key JSON needs rotors, positions, rings, and plugboard arrays.');
        key = data;
      }
      renderRotors(); status(`Imported ${kind} settings. The shared Python core validates them before processing.`);
    } catch (error) { status(error.message, true); }
    finally { target.value = ''; }
  });
}
$('add-rotor').addEventListener('click', () => {
  const next = Object.keys(machine.rotors).find((name) => !key.rotors.includes(name));
  if (!next || key.rotors.length >= 8) return;
  key.rotors.push(next); key.positions.push(0); key.rings.push(0); renderRotors();
});
$('plugboard').addEventListener('change', () => { key.plugboard = $('plugboard').value.trim().split(/\s+/).filter(Boolean); rotorSummary(); });
function countBytes() { $('byte-count').textContent = `${$('plaintext').value.length} / 512 bytes`; }
$('plaintext').addEventListener('input', countBytes); countBytes();
$('scenario').addEventListener('change', () => {
  if ($('scenario').value === 'lost-block') {
    $('mode').value = 'checked';
    if ($('plaintext').value.length < 33) $('plaintext').value = 'First block here.Next block lost!Later blocks recover.\n';
    countBytes();
  }
});
$('mode').addEventListener('change', () => {
  if ($('mode').value !== 'checked' && $('scenario').value === 'lost-block') $('scenario').value = 'clean';
});

function send(message) {
  if (active?.ws?.readyState === WebSocket.OPEN) active.ws.send(JSON.stringify(message));
}
async function cleanup(live, closeSocket = true) {
  if (!live || live.cleaning) return;
  live.cleaning = true;
  live.capture?.disconnect(); live.source?.disconnect(); live.silentGain?.disconnect();
  live.stream?.getTracks().forEach((track) => track.stop());
  live.playing.forEach((source) => { try { source.stop(); } catch {} }); live.playing.clear();
  if (live.context?.state !== 'closed') await live.context?.close().catch(() => {});
  if (closeSocket) live.ws?.close();
  if (active === live) active = null;
  $('begin').hidden = true; $('stream-controls').hidden = true; controls();
}
function queuePlayback(live, buffer) {
  if (live.cleaning) return;
  const pcm = new Float32Array(buffer);
  const context = live.context;
  const output = context.createBuffer(1, pcm.length, context.sampleRate); output.copyToChannel(pcm, 0);
  const source = context.createBufferSource(); source.buffer = output; source.connect(context.destination);
  if (live.nextTime < context.currentTime && live.hasPlayed) {
    send({type:'stop'}); status('Playback underrun: audio continuity was lost. Transmission stopped.', true); badge('AUDIO ERROR'); cleanup(live); return;
  }
  if (!live.hasPlayed) live.nextTime = context.currentTime + 0.1;
  if (live.nextTime - context.currentTime > 2.2) {
    send({type:'stop'}); status('Playback queue exceeded two seconds. Transmission stopped.', true); cleanup(live); return;
  }
  source.start(live.nextTime); live.nextTime += pcm.length / context.sampleRate; live.hasPlayed = true; live.playing.add(source);
  source.onended = () => { live.playing.delete(source); source.disconnect(); if (!live.cleaning) send({type:'ack', samples:pcm.length}); };
}
async function startLive(operation) {
  if (active || busy) return;
  let live;
  try {
    const settings = options();
    const context = new AudioContext();
    live = {operation, context, playing:new Set(), pending:0, nextTime:0, cleaning:false, hasPlayed:false, finishing:false};
    active = live; controls();
    await context.resume();
    if (live.cleaning) return;
    if (![44100,48000].includes(context.sampleRate)) throw new Error(`The browser selected ${context.sampleRate} Hz; this demo supports 44100 or 48000 Hz.`);
    clearStages(); $('playback').pause(); $('playback').removeAttribute('src'); $('playback').load();
    $('download').removeAttribute('href'); $('download').classList.add('disabled'); $('download').setAttribute('aria-disabled', 'true');
    $('duration').textContent = '—'; $('audio-note').textContent = 'Live hardware operation. No offline recording is attached.';
    $('channel-tag').textContent = 'LIVE'; badge(operation === 'rx' ? 'LISTENING' : 'PREPARING');
    status(operation === 'rx' ? 'Requesting microphone access…' : 'Preparing the actual transmitted symbols…');
    if (operation === 'rx') {
      // Permission request is directly tied to this explicit user action.
      live.stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1, echoCancellation:false, noiseSuppression:false, autoGainControl:false}});
      if (live.cleaning) { live.stream.getTracks().forEach((track) => track.stop()); return; }
    }
    live.ws = new WebSocket(`ws://${location.host}/api/live?session=${session}`); live.ws.binaryType = 'arraybuffer';
    live.ws.onopen = () => {
      if (live.cleaning) return live.ws.close();
      live.ws.send(JSON.stringify({...settings, type:'start', operation, sample_rate:context.sampleRate, text:$('plaintext').value, streaming:$('streaming').checked}));
    };
    live.ws.onmessage = async ({data}) => {
      if (live.cleaning) return;
      try {
        if (data instanceof ArrayBuffer) { queuePlayback(live, data); return; }
        const event = JSON.parse(data);
        if (event.type === 'ready') {
          if (operation === 'tx') {
            $('duration').textContent = duration(event.duration); $('ciphertext').textContent = event.symbols;
            $('begin').hidden = false; $('begin').textContent = `Play ${duration(event.duration)}${event.streaming ? ' + stream' : ''}`;
            status(`Live transmission prepared: ${duration(event.duration)}${event.streaming ? ' of initial audio; appended text adds more' : ''}. Press Play transmission to begin.`);
            $('audio-note').textContent = event.streaming ? 'Initial transmission duration; appended text adds audio.' : 'Prepared live transmission. Audio begins only when you press Play.';
            badge('PREPARED');
          } else {
            // Reuse the permission-approved stream; avoid a second permission/device request.
            await context.audioWorklet.addModule('/static/capture-worklet.js');
            if (live.cleaning) return;
            live.capture = new AudioWorkletNode(context, 'er-capture');
            live.source = context.createMediaStreamSource(live.stream);
            live.silentGain = context.createGain(); live.silentGain.gain.value = 0;
            live.capture.port.onmessage = ({data:samples}) => {
              if (samples.flushed) { send({type:'end'}); return; }
              if (samples.discontinuity) {
                live.finishing = true; send({type:'discontinuity'}); send({type:'end'});
                live.stream.getTracks().forEach((track) => track.stop()); live.capture.disconnect();
                status(`${samples.discontinuity} A discontinuity was reported; reception stopped.`, true); return;
              }
              if (live.cleaning || live.ws.readyState !== WebSocket.OPEN) return;
              if (live.pending + samples.length > 2 * context.sampleRate || live.ws.bufferedAmount > 8 * context.sampleRate) {
                send({type:'discontinuity'}); send({type:'end'}); live.finishing = true;
                live.stream.getTracks().forEach((track) => track.stop()); live.capture.disconnect();
                status('Microphone queue exceeded two seconds. Discontinuity reported; reception stopped.', true); return;
              }
              live.pending += samples.length; live.ws.send(samples.buffer);
            };
            live.source.connect(live.capture); live.capture.connect(live.silentGain); live.silentGain.connect(context.destination);
            live.stream.getAudioTracks()[0].addEventListener('ended', () => { if (!live.cleaning && !live.finishing) { send({type:'discontinuity'}); send({type:'end'}); status('Microphone capture ended unexpectedly.', true); }});
            status(`Live microphone reception at ${context.sampleRate.toLocaleString()} Hz. Waiting for a Morse signal…`);
            $('duration').textContent = 'LIVE';
          }
        } else if (event.type === 'symbols') {
          if (!live.playing.size) live.hasPlayed = false;
          if (!live.symbolsStarted) { $('ciphertext').textContent = ''; live.symbolsStarted = true; }
          $('ciphertext').textContent += event.symbols;
        } else if (event.type === 'received') {
          live.pending = Math.max(0, live.pending - event.ack);
          if (event.ack > 0) live.capture?.port.postMessage({ack:event.ack});
          $('received').textContent += event.symbols || ''; $('recovered').textContent += event.recovered || '';
        } else if (event.type === 'draining') {
          status('Finishing transmission: waiting for queued audio to play…');
        } else if (event.type === 'complete') {
          $('received').textContent += event.symbols || ''; $('recovered').textContent += event.recovered || '';
          $('duration').textContent = duration(event.duration); diagnostics(event.errors); badge(event.success ? 'LIVE COMPLETE' : 'CHECK DIAGNOSTICS');
          status(operation === 'tx' ? 'Live playback completed. Use a separate receiving device to verify the audio path.' : (event.success ? 'Live reception complete. Review the recovered message.' : 'Live reception finished with errors. Review diagnostics.'), !event.success);
          await cleanup(live);
        } else if (event.type === 'error') { status(event.error, true); badge('ERROR'); await cleanup(live); }
      } catch (error) { status(error.message, true); badge('ERROR'); await cleanup(live); }
    };
    live.ws.onerror = () => { if (live.cleaning) return; status('The live connection failed. Confirm that the local server is running.', true); badge('ERROR'); cleanup(live); };
    live.ws.onclose = () => {
      if (!live.cleaning) { status('Live connection closed. Audio and microphone resources have been released.'); badge('STOPPED'); cleanup(live, false); }
    };
  } catch (error) {
    if (live?.cleaning) return;
    status(error.name === 'NotAllowedError' ? 'Microphone access was denied. Enable it in browser permissions to receive live audio, or upload a WAV.' : error.message, true);
    badge('ERROR'); await cleanup(live); controls();
  }
}
$('live-tx').addEventListener('click', () => startLive('tx'));
$('live-rx').addEventListener('click', () => startLive('rx'));
$('begin').addEventListener('click', async () => {
  if (!active) return;
  await active.context.resume(); send({type:'begin'}); $('begin').hidden = true;
  $('stream-controls').hidden = !$('streaming').checked; badge('TRANSMITTING'); status('Playing the live Morse transmission…');
});
$('send-chunk').addEventListener('click', () => {
  const text = $('stream-text').value;
  if (!text) return;
  send({type:'text', text}); $('stream-text').value = ''; status('Text added to the open transmission. Checked blocks flush after five idle seconds.');
});
$('end-stream').addEventListener('click', () => { send({type:'end'}); $('stream-controls').hidden = true; status('Finishing the stream and draining queued audio…'); });
$('finish-rx').addEventListener('click', () => {
  if (!active?.capture) return;
  active.finishing = true; active.capture.port.postMessage('flush'); active.stream.getTracks().forEach((track) => track.stop()); $('finish-rx').disabled = true;
  status('Finishing reception and validating any final frame…');
});
$('stop').addEventListener('click', () => { if (busy) { offlineController?.abort(); return; } send({type:'stop'}); cleanup(active); badge('STOPPED'); status('Live operation stopped. Microphone and playback resources released.'); });
window.addEventListener('pagehide', () => { offlineController?.abort(); send({type:'stop'}); cleanup(active); });

controls();
try {
  const config = await api('/api/config'); machine = config.machine; key = config.key; renderRotors(); controls();
} catch (error) { status(`Could not load configuration: ${error.message}`, true); controls(); }
