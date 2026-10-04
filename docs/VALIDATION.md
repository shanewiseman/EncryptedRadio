# Validation and acceptance

## Reproduce the automated checks

```sh
make sync
make check
make demo
uv run --locked --extra audio --extra demo er-demo roundtrip --scenario noisy --output-dir tmp/demo-noisy
uv run --locked --extra audio --extra demo er-demo roundtrip --scenario lost-block --output-dir tmp/demo-loss
uv run --locked --extra audio python scripts/benchmark_dsp.py --output tmp/dsp-matrix.json
```

The full suite includes `sealcrypt`. To run its focused protocol and CLI tests:

```sh
uv run --locked --extra audio --extra demo python -m unittest discover -s tests -p 'test_seal.py' -v
```

`make demo` and the browser presets exercise the rotor cipher. The focused seal
tests exercise its own authenticated protocol and the shared Morse WAV transport;
they do not add `sealcrypt` to the browser demo.

The CI job remains named `Repository checks`, preserving the existing protection
requirement. It installs locked dependencies and PortAudio, runs hygiene and tests,
and executes the terminal demonstration. It does not open an audio device.

Initial rotor/audio implementation validation on 2026-10-03 passed all 72 tests,
repository hygiene, clean/noisy/lost-block terminal demos, and a complete shell pipeline through both
CLIs with byte-for-byte output comparison. Both wheel and source distribution builds
passed; the wheel includes public JSON resources and browser static assets.

The latest recorded implementation baseline, including sealcrypt, passed the full
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

## Automated acceptance coverage

| Area | Evidence |
| --- | --- |
| Rotor cipher/configuration | Independent affine vector, double-step/turnover, rings, 3–8 rotors, 10–16 plugs, malformed configurations, reciprocal reflector |
| Both cipher CLIs: ASCII/streaming | All 128 bytes, arbitrary chunk boundaries, immediate raw pipe output, idle checked flush, finite batch/file input, broken pipes |
| Rotor checked protocol | Checksums, wrong key/machine, missing/duplicate/old/reordered frames, oversized/truncated bodies, missing end, resynchronization, sequence exhaustion, bounded errors |
| sealcrypt authenticated protocol | Independent wire/key-derivation vectors, verified-only plaintext release, key/mode/machine binding, checked recovery, raw failure on errors, authenticated end markers, session randomness, bounds and sequence exhaustion |
| sealcrypt keys | Strict schema, private file/directory creation, existing-path refusal, no key material in command output |
| Audio | All 49 symbols, word spaces, independent keyed fixtures, sample rates, long silence/noise-only input, uncertainty, invalid PCM |
| Device adapters | Mocked capture overflow, playback underrun, unavailable devices, queued drain and intentional stdin pauses; no physical hardware claim |
| Terminal demo | Actual PCM round trips, clean/noisy/lost-block scenarios, byte comparison, decoder failure injection and exit statuses |
| Browser backend | Real offline pipeline, WAV upload/download, 44.1/48 kHz live PCM, Host/Origin rejection, limits, ACK backpressure, streaming, Stop/disconnect and temporary cleanup |
| Browser lifecycle | Node stubs execute the real JavaScript: microphone denial, actual sample rate, double-click exclusion, scheduling, cleanup and AudioWorklet credits while the main thread stalls |

## DSP matrix results

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

## Browser smoke procedure

Run `make demo-web`, visit <http://127.0.0.1:8765>, and exercise:

1. Default checked round trip: exact byte match, real symbols in each panel, WAV
   duration shown, download/playback available. Repeat noisy and lost-block presets.
2. Raw and text modes; modify ordered rotors, positions, rings and plugs; import
   machine/key JSON. Invalid settings must show an error rather than start audio.
3. WAV upload at 44.1 and 48 kHz; live preparation must show duration before Play.
   Stop must restore controls and close the WebSocket/audio context.
4. Deny microphone permission: show an actionable error, allow another operation,
   leave no active capture. Stop while permission is pending must stop a late stream.
5. Start/stop streaming TX; append text and finish; receive PCM; close the tab during
   a live operation. Verify tracks/context/backend sessions are released.
6. Disconnect during an offline job: worker cancellation and temporary cleanup.
   Exercise input/upload/duration limits without allocating full recordings.

Browser UI smoke checks and mocked lifecycle checks are not acoustic measurements.

During implementation, the in-app browser passed the default checked, noisy and
lost-block presets. A prepared 1.9-second `SOS` playback completed with no browser
errors. PortAudio loaded from locally extracted distribution packages and listed
the Linux audio devices. Enumeration and playback-control completion do not verify
that a separate physical microphone recovered the transmitted sound.

## Separate physical acceptance — not yet completed

The implementation session did not validate an acoustic speaker-to-microphone path
or a real human operator. Keep these as explicit remaining physical acceptance
tests; do not replace them with synthetic successes.

1. On Linux with PortAudio installed, record OS, audio device IDs, sample rates,
   microphone placement, volume and ambient conditions. Enumerate with
   `morselink devices`; use two processes/devices for half-duplex TX and RX.
2. At comfortable speaker volume, transmit a checked rotor message using public
   demonstration settings into an independent microphone receiver and compare the
   plaintext file byte-for-byte. Separately repeat with `sealcrypt` and a generated
   test key shared by the two endpoints; use synthetic plaintext for both ciphers.
   Repeat default 700 Hz/20 WPM, then frequency/speed edges at both rates.
3. Introduce a brief acoustic interruption: require a reported error/gap and later
   checked-block recovery. Deliberately stall capture output and verify sample-loss
   reporting. Stop each direction and verify the device can be reopened.
4. Have an operator hand-key mixed dots/dashes and punctuation within 8–30 WPM.
   Capture a consented fixture, record timing/signal conditions and compare against
   the intended text. Test both automatic reception and manual overrides. Record
   failures, including ambiguous startup; do not apply language corrections.
5. Repeat browser permission denial, actual playback/capture and Stop/tab-close
   while watching the operating system's microphone indicator.

RF hardware, station interference, radio rules and production cryptographic review
remain outside this release's acceptance scope.
