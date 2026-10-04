# Validation and acceptance

## Reproduce the automated checks

```sh
make sync
make check
make demo
uv run --locked --extra audio --extra demo er-demo roundtrip --scenario noisy --output-dir tmp/demo-noisy
uv run --locked --extra audio --extra demo er-demo roundtrip --scenario lost-block --output-dir tmp/demo-loss
uv run --locked --extra audio python scripts/benchmark_dsp.py --output tmp/dsp-matrix.json
uv run --locked --extra demo python scripts/benchmark_transports.py --output-dir tmp/audiolink-comparison
```

The full suite includes `sealcrypt`. To run its focused protocol and CLI tests:

```sh
uv run --locked --extra audio --extra demo python -m unittest discover -s tests -p 'test_seal.py' -v
```

`make demo` preserves the default rotor/Morse round trip. The terminal and browser
also select either cipher and transport. Exercise the affected combinations with:

```sh
er-demo roundtrip --cipher rotorcrypt --transport audiolink --output-dir tmp/check-rotor-afsk
er-demo roundtrip --cipher sealcrypt --transport morselink --output-dir tmp/check-seal-morse
er-demo roundtrip --cipher sealcrypt --transport audiolink --output-dir tmp/check-seal-afsk
```

These demonstrations pass through synthesized PCM and the actual decoder. The
selected cipher's protocol tests remain necessary alongside transport checks.

The CI job remains named `Repository checks`, preserving the existing protection
requirement. It installs locked dependencies and PortAudio, runs hygiene and tests,
and executes the default rotor/Morse and explicit sealcrypt/audiolink terminal
demonstrations. It does not open an audio device.

Initial rotor/audio implementation validation on 2026-10-03 passed all 72 tests,
repository hygiene, clean/noisy/lost-block terminal demos, and a complete shell pipeline through both
CLIs with byte-for-byte output comparison. Both wheel and source distribution builds
passed; the wheel includes public JSON resources and browser static assets.

The pre-audiolink implementation baseline, including sealcrypt, passed the full
**95-test** suite, including 23 new authenticated-cipher tests. Both checked and raw shell pipelines passed
`sealcrypt → morselink WAV → morselink decode → sealcrypt` with byte-for-byte
comparison. The original `make demo` and both package builds also passed.

The seal tests include fixed wire vectors with independent HMAC-based HKDF
derivation, all ASCII/chunk combinations, authentication failures, wrong keys and
contexts, loss/reordering/recovery, raw failure behavior, truncation/end markers,
sequence exhaustion, bounded parsing, private key permissions/no-overwrite, CLI
idle/immediate streaming, argument ordering, interruptions and broken pipes. A
separate review exercised all 536 single-bit mutations of one packet and 676
truncated checked/raw streams. This is functional/security regression evidence,
not an independent cryptographic audit. See [sealcrypt protocol](SEALCRYPT.md).

The audiolink and demo integration passed **127 tests** in `make check`, including
22 focused modem/CLI tests, plus repository hygiene. `make demo` passed the
default rotor/Morse round trip, and an explicit sealcrypt/audiolink terminal demo
passed. Installed command pipelines in both checked and raw modes recovered all
128 ASCII values repeated twice (256 bytes) through
`sealcrypt → audiolink WAV → audiolink decode → sealcrypt`, with exact byte
comparison and zero exit statuses. Wheel and source-distribution builds passed.
The reproducible modem matrix and transport comparison below record the signal
conditions rather than implying physical-device validation.

The initial optional lowercase-first implementation passed **156 tests** in `make check`, including
29 new test methods and expanded browser selection assertions, plus repository
hygiene. `make sync` and the default `make demo` passed. New coverage includes
all 128 ASCII values across chunk boundaries, exact capitalization, original-byte
rotor CRCs, unchanged legacy wire vectors, framed encoding mismatches, unknown
flags, authenticated flag tampering, and matching end records. Seal authentication
failures neither release plaintext nor advance session/sequence state.

Separate installed-command WAV pipelines passed all eight combinations of
`rotorcrypt|sealcrypt` × `raw|checked` × `morselink|audiolink` with
`--text-encoding lowercase-first` on both cipher endpoints. The 47-byte example
`This message is encrypted using wwii technology` was recovered exactly in every
case. It used 61 raw rotor symbols (139 with legacy encoding), 224 checked rotor
symbols, and 297 seal symbols in either mode. Seal encoding changes no byte count.

Browser tests cover encoding in round trips, uploaded WAVs, mismatched settings,
and streaming live TX/RX through actual generated PCM for both ciphers and modes.
A local browser smoke check also selected lowercase-first/raw/Morse and recovered
the exact example above; the selector and result layout were visually reviewed.
These checks use synthetic PCM and do not establish physical audio compatibility.

The lowercase-first default change in [ADR 0006](decisions/0006-default-lowercase-first.md)
passed **162 tests** and hygiene in `make check`, plus `make sync` and `make demo`.
Legacy vectors are now checked using explicit uppercase-first selection; `ascii`
remains a tested alias. Tests also cover the shorthand override, conflicting CLI
options, bare seal key generation, omitted browser settings and text-mode behavior.

All **16 installed-command WAV pipelines** passed for both ciphers, both modes,
both transports and either omitted encoding (lowercase-first) or
`--uppercase-first` on both ends. Every pipeline recovered the original 47-byte
example exactly. Raw rotor output was 61 symbols by default and 139 with the
override. A browser smoke check separately confirmed its initial lowercase-first
selection and exact-case recovery with both encoding choices. The packet formats,
authenticated fields and transport algorithms did not change with the default.

To reproduce a lowercase-first terminal demo (repeat for each cipher, mode and
transport), use:

```sh
er-demo roundtrip --cipher rotorcrypt --transport morselink --mode raw \
  --text 'This message is encrypted using wwii technology' \
  --output-dir tmp/demo-lowercase-first
```

Add `--uppercase-first` to exercise the original encoding instead. Previously
recorded ciphertext using the original default needs that override at decryption.

## Automated acceptance coverage

| Area | Evidence |
| --- | --- |
| Rotor cipher/configuration | Independent affine vector, double-step/turnover, rings, 3–8 rotors, 10–16 plugs, malformed configurations, reciprocal reflector |
| Both cipher CLIs: ASCII/streaming | All 128 bytes, arbitrary chunk boundaries, immediate raw pipe output, idle checked flush, finite batch/file input, broken pipes |
| Both cipher text encodings | Lowercase default and explicit legacy compatibility, all ASCII and exact case, shorter lowercase rotor prose, encoding markers and mismatch rejection, seal flag authentication, CLI/browser propagation |
| Rotor checked protocol | Checksums, wrong key/machine, missing/duplicate/old/reordered frames, oversized/truncated bodies, missing end, resynchronization, sequence exhaustion, bounded errors |
| sealcrypt authenticated protocol | Independent wire/key-derivation vectors, verified-only plaintext release, key/mode/machine binding, checked recovery, raw failure on errors, authenticated end markers, session randomness, bounds and sequence exhaustion |
| sealcrypt keys | Strict schema, private file/directory creation, existing-path refusal, no key material in command output |
| Morse audio | All 49 symbols, word spaces, independent keyed fixtures, sample rates, long silence/noise-only input, uncertainty, invalid PCM |
| Packet audio | Independent Hamming vectors, correction/detection through actual corrupted PCM, all ASCII, arbitrary chunks, loss/duplicates/reordering, end/truncation recovery, sample clocks, bounded silence/noise and session bookkeeping |
| Device adapters | Mocked capture overflow, playback underrun, unavailable devices, queued drain and intentional stdin pauses; no physical hardware claim |
| Terminal demo | All four cipher/transport pairs in checked/raw modes; actual PCM clean/noisy/lost-block scenarios, byte comparison, decoder failure injection and exit statuses |
| Browser backend | Cipher/transport selection through the real pipeline, generated/imported seal keys, key-free artifacts, WAV upload/download, 44.1/48 kHz live PCM, Host/Origin rejection, limits, ACK backpressure, streaming, Stop/disconnect and temporary cleanup |
| Browser lifecycle | Node stubs execute real JavaScript: selections, key generation/import with no browser storage, microphone denial, actual sample rate, double-click exclusion, intentional streaming pauses, underruns, cleanup and AudioWorklet credits while the main thread stalls |

## Morse DSP matrix results

Measured with Python 3.12.3, NumPy 2.5.3, SciPy 1.18.1 on Linux. Each row covers
44,100/48,000 Hz × 400/700/1,200 Hz × 8/20/30 WPM (18 cases). The independently
keyed fixture is `VVV(ABC234)`, seed 218. Every tone and gap has bounded random
timing variation; Gaussian noise is band-limited to 350–1250 Hz. SNR uses average
signal/noise power over the whole fixture, including gaps. The receiver receives
only PCM and sample rate, with automatic pitch and speed acquisition.

| Noise SNR | Timing jitter | Exact cases | Edit errors / expected characters | Character error rate |
| --- | --- | --- | --- | --- |
| 10 dB, mandatory | ±20% | 18/18 | 0/198 | 0% |
| 0 dB, exploratory | ±30% | 0/18 | 400/198 | 202.0% |
| −5 dB, exploratory | ±40% | 0/18 | 1032/198 | 521.2% |

Character error rate is Levenshtein edits divided by expected characters; insertions
can make it exceed 100%. Harder rows characterize failure outside the initial
envelope and are not advertised as supported. This finite reproducible matrix does
not prove exact reception for every message, noise realization or human operator.
The benchmark writes individual recovered strings and error counts to JSON and
fails its exit status if a mandatory case fails.

The terminal noisy demo separately uses seeded 300–3000 Hz noise at 10 dB. The loss
demo removes a complete frame's real PCM span. Its success requires the exact
remaining plaintext and a reported gap, not an intact-message claim. Its artifacts
include the original, cipher symbols, WAV, received symbols, recovered bytes and
JSON report with actual removed sample bounds.

## Packet audio DSP matrix

The focused modem checks are reproducible without audio hardware:

```sh
uv run --locked --extra audio --extra demo python -m unittest discover -s tests -p 'test_audiolink.py' -v
```

`test_reproducible_voice_band_dsp_matrix` generates 393 ASCII bytes using NumPy
seed 43 and a public transport session `AFSKtest`. It decodes PCM in repeating
137/960/4,093/1,024-sample chunks without expected-payload or packet-boundary hints.
The 22 main cases combine 44,100/48,000 Hz with these eleven fixtures:

- Clean PCM and a causal fourth-order Butterworth 300–3,000 Hz band-pass.
- Filtered signal plus 10 dB noise band-limited through the same filter.
- Filtered signal plus a first-order 1 kHz low-pass representing de-emphasis.
- Filtered signal clipped to ±0.2 full scale.
- Filtering, de-emphasis, clipping and 10 dB noise combined.
- Filtered signals resampled at −1,000 and +1,000 ppm clock mismatch.
- Combined impaired signals resampled at those same two clock mismatches.
- Filtered signal with its first 150 ms and last 25 ms removed, inside the
  configured acquisition lead and end tail guards.

Noise uses seed 20261003. The 10 dB ratio is measured from average signal and noise
power over the entire waveform, including guards/silence, after the selected
filtering, de-emphasis and clipping. Two additional cases use maximum-size
256-byte packets and ±700 ppm clock mismatch, between the decoder's trial rates.

All 24 fixtures recovered the exact payload without diagnostics; the main cases
also explicitly verify receipt of the end packet. Separate tests introduce actual
coded header/body PCM corruption, exercise Hamming correction and CRC rejection,
and verify subsequent checked-packet recovery or raw failure. These finite cases
establish the declared synthetic envelope, not a general guarantee for arbitrary
noise, speech processing, companding, multiple signals or physical radios.

## Voice-band transport comparison

The recorded 2026-10-04 UTC comparison uses this exact 20-word, 107-byte message,
without a trailing newline:

```text
Meet me at the old bridge tomorrow morning and bring the blue notebook so we can finish our secret project.
```

Run `scripts/benchmark_transports.py` with the command above. It synthesizes mono
48 kHz PCM16 WAVs, applies the same causal third-order Butterworth 300–3,000 Hz
band-pass to each, and invokes each transport's real PCM decoder. This particular
comparison has no added noise. Text mode compares against normalized uppercase
text; checked mode encrypts once and sends the identical 393-symbol sealcrypt
stream through both transports before authenticated decryption. Cipher sessions
remain randomly generated, so a later run can have a different Morse duration;
audiolink airtime depends on the packet lengths rather than character identity.
After a run, add `--ciphertext tmp/audiolink-comparison/ciphertext.txt` to reuse
its saved public benchmark fixture and reproduce its exact Morse timing.

| Payload | Morse at 20 WPM / 700 Hz | audiolink at default settings | Speedup | Airtime reduction |
| --- | --- | --- | --- | --- |
| Ordinary text | 54.54 s | 2.887 s | 18.89× | 94.71% |
| sealcrypt checked | 276.90 s | 8.89 s | 31.15× | 96.79% |

All four cases recovered the exact transmitted symbols (normalized uppercase in
text mode) and expected plaintext without decoder diagnostics. Durations come from actual WAV frame counts and include acquisition, framing,
error correction, guards and end signaling. The generated input, cipher stream,
clean/filtered WAVs and JSON report are saved in the ignored output directory.
The benchmark returns nonzero when a required round trip fails.

These results establish software behavior under the stated filter, not measured
GXT3000 response, acoustic performance, physical range or radio interoperability.
The earlier full-band ggwave trial used a different waveform and is not evidence
for audiolink's supported voice-band envelope. See [AUDIOLINK.md](AUDIOLINK.md).

## Browser smoke procedure

Run `make demo-web`, visit <http://127.0.0.1:8765>, and exercise:

1. Default checked round trip: exact byte match, real symbols in each panel, WAV
   duration shown, download/playback available. Repeat all four cipher/transport
   combinations and the noisy/lost-block presets.
2. Raw and text modes; modify ordered rotors, positions, rings and plugs; import
   machine/key JSON. Select sealcrypt, generate/import its distinct key and decode
   with the matching key. Invalid settings must show an error rather than start
   audio. Changing transport must use that transport's controls and waveform.
3. WAV upload at 44.1 and 48 kHz; live preparation must show duration before Play.
   Stop must restore controls and close the WebSocket/audio context.
4. Deny microphone permission: show an actionable error, allow another operation,
   leave no active capture. Stop while permission is pending must stop a late stream.
5. Start/stop streaming TX; append text and finish; receive PCM; close the tab during
   a live operation. Verify tracks/context/backend sessions are released.
6. Disconnect during an offline job: worker cancellation and temporary cleanup.
   Exercise input/upload/duration limits without allocating full recordings.
7. Choose **Acoustic round trip**, allow the microphone, inspect the prepared
   duration and click **Play**. Verify capture starts before playback and reception
   finishes after playback drains, a one-second tail measured by the audio clock,
   and a flush of queued samples. Inspect the microphone result, exact match
   (normalized match in text mode) and diagnostics.
   Repeat both ciphers/transports, checked/raw/text modes and both text encodings
   where applicable. Keep physical results separate from injected PCM or browser
   audio mocks.
8. For acoustic round trip, deny microphone access, Stop while permission is
   pending, Stop before Play, Stop during playback and close the tab mid-transfer.
   Verify both directions release their resources and a new operation can start.
   Exercise capture overflow, playback underrun and disconnect failures; none may
   produce a successful completed-match result.

Browser UI smoke checks and mocked lifecycle checks are not acoustic measurements.
The audiolink integration was exercised in the actual in-app browser: all four
cipher/transport clean round trips recovered exact input, and sealcrypt/audiolink
passed the noisy and lost-block recovery presets. A sealcrypt/audiolink live
transmission prepared with a displayed 5.4-second duration; Stop released the
operation and a subsequent offline round trip succeeded. These actions use the
real backend PCM decoder and preparation path; no new physical speaker/microphone
test was performed.

During the initial Morse implementation, the in-app browser passed the default checked, noisy and
lost-block presets. A prepared 1.9-second `SOS` playback completed with no browser
errors. PortAudio loaded from locally extracted distribution packages and listed
the Linux audio devices. Enumeration and playback-control completion do not verify
that a separate physical microphone recovered the transmitted sound.

## Single-tab acoustic acceptance status

The requested workflow follows an informal user trial of speaker transmission and
microphone reception using two external browser tabs. The user reported a positive
experience; no device settings, signal conditions, exact recovered bytes or
repeatability measurements were recorded. That report motivates the single-tab
workflow but does not establish a measured acoustic envelope.

During single-tab implementation, `make sync`, `make check` and `make demo` passed.
The default rotor/Morse demo recovered its message exactly without diagnostics;
its synthesized waveform was 105.66 seconds long.

`tests/test_web_acoustic.py` verifies 16 actual PCM round trips across both ciphers,
both transports, raw/checked modes and both encodings, using 48 kHz for
lowercase-first and 44.1 kHz for uppercase-first. It also checks normalized text,
silence, mismatches, missing end frames, independent duration/credit limits,
invalid PCM and cancellation. Twelve abrupt TCP disconnects followed by reuse of
the same session verify that failed sends cannot leave the browser locked out.
`tests/test_web_acoustic_frontend.py` executes the JavaScript with stub devices to
check microphone readiness before Play, independent playback/capture, tail flush,
failure reporting, cleanup and stale asynchronous callbacks.

The updated control was visibly enabled in external Chrome. No microphone capture
or audible playback was initiated during that UI check. These injected-PCM and
mocked-device checks establish software behavior; measured physical recovery
remains pending. See [task acceptance](tasks/acoustic-round-trip.md).

## Separate physical acceptance — not yet completed

Measured speaker-to-microphone acceptance for the single-tab workflow and real
human-keying acceptance remain incomplete. Keep these as explicit physical tests;
do not replace them with synthetic successes.

1. On Linux with PortAudio installed, record OS, audio device IDs, sample rates,
   microphone placement, volume and ambient conditions. Enumerate with
   `morselink devices`; use two processes/devices for half-duplex TX and RX.
2. At comfortable speaker volume, transmit a checked rotor message using public
   demonstration settings into an independent microphone receiver and compare the
   plaintext file byte-for-byte. Separately repeat with `sealcrypt` and a generated
   test key shared by the two endpoints; use synthetic plaintext for both ciphers.
   Repeat Morse default 700 Hz/20 WPM, then frequency/speed edges at both rates.
   Separately exercise audiolink at 1,200/2,200 Hz with both ciphers and rates;
   record channel filtering, levels, distortion and burst startup behavior.
3. Introduce a brief acoustic interruption: require a reported error/gap and later
   checked-block recovery. Deliberately stall capture output and verify sample-loss
   reporting. Stop each direction and verify the device can be reopened.
4. Have an operator hand-key mixed dots/dashes and punctuation within 8–30 WPM.
   Capture a consented fixture, record timing/signal conditions and compare against
   the intended text. Test both automatic reception and manual overrides. Record
   failures, including ambiguous startup; do not apply language corrections.
5. Repeat browser permission denial, actual playback/capture and Stop/tab-close
   while watching the operating system's microphone indicator.
6. Run the single-tab **Acoustic round trip** procedure above with a short public
   test message. Record browser/OS, devices, selected sample rate, microphone
   processing settings, speaker volume, placement and ambient conditions alongside
   recovered text, comparison and diagnostics. Repeat each cipher/transport and
   checked/raw/text mode, including both text encodings where applicable. An
   incomplete or failed receive must remain visible even if some text is recovered.

RF hardware, station interference, radio rules and production cryptographic review
remain outside this release's acceptance scope.
