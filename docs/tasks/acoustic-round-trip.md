# Single-tab acoustic round trip

## Objective

Let a user exercise a speaker → air → microphone transfer within one browser tab,
with actual decoding, finite completion, plaintext comparison and visible failures.
This follows an informal two-tab user trial; that trial supplied no measured
physical acceptance evidence.

## Scope and constraints

- Add **Acoustic round trip** beside the browser's transmit and receive actions.
  Request microphone access on the explicit action, arm capture before **Play**,
  and show the actual prepared duration before speaker playback begins.
- Send the complete current message using the selected cipher, transport, mode,
  configuration, key and encoding in both directions. Support rotorcrypt and
  sealcrypt with Morse and packet audio, checked/raw/text modes and both cipher
  encodings. Reject empty messages, including ordinary text that normalizes to
  empty. Streaming append remains a standalone TX feature.
- Use one active WebSocket operation per browser session, with independent TX/RX
  state and bounded credits. Only microphone PCM enters the existing Python
  receiver; JavaScript does not decode, fabricate output or loop generated PCM
  directly into reception. Never monitor microphone audio through the speakers.
- After playback drains, keep capture active for one second measured by the
  AudioContext clock, then flush queued samples before receiver EOF. Compare
  actual received plaintext to the original input; ordinary text
  compares against the selected transport's normalization and is labeled accordingly.
- Show microphone results and decoder diagnostics separately from offline results.
  Stop, disconnect, permission failures and audio discontinuities must clean up
  both directions and permit another operation.
- Preserve cipher/DSP authority, protocol formats, seal authentication before
  plaintext release, random sessions, queue bounds and configuration limits.
  No cipher, modem, RF-control or protocol redesign is in scope.

## Acceptance criteria

- [x] One tab can prepare a finite transmission, arm microphone capture, show
  duration, play through speakers and automatically finish reception.
- [x] Both ciphers/transports and checked/raw/text modes use actual receiver output;
  both cipher encodings retain exact original bytes. Text labels its normalized
  comparison rather than claiming byte-for-byte preservation of input.
- [x] Playback completion and receive completion are distinct; final capture tail
  and queued PCM drain before decoder EOF and comparison.
- [x] Empty messages and whitespace-only normalized text are rejected before
  transmission; absent microphone recovery cannot produce a successful match.
- [x] Permission denial, late permission after Stop, Stop at each lifecycle stage,
  disconnect, overflow and underrun clean up both directions without reporting a
  false successful transfer. A subsequent operation is allowed.
- [x] Existing independent TX/RX, streaming TX, offline and WAV flows retain their
  behavior; one browser session still excludes concurrent operations.
- [x] Repository checks, default demo and affected-combination checks pass, and
  documentation distinguishes automated evidence from physical acceptance.

## Verification

Run `make sync`, `make check` and `make demo`. Add focused backend tests that feed
the actual emitted PCM into the existing receiver across the affected
cipher/transport/mode/encoding combinations. Cover silence/incomplete input and
finite decoder failures as well as successful byte comparisons. Browser lifecycle
tests should verify permission ordering, separate credits, drain/tail completion,
Stop/disconnect, resource release and recoverability after errors. Use the
[browser smoke procedure](../VALIDATION.md#browser-smoke-procedure) and record only
checks actually performed.

Physical acceptance needs an available speaker and microphone and must be reported
separately with device/browser settings and comparison evidence. Synthetic PCM and
mocked device tests cannot establish room-acoustic or radio compatibility.

## Security and external effects

Use synthetic plaintext and public demonstration configuration. Seal test keys
remain in memory and are not included in reports or logs. Microphone permission
and audible playback require explicit UI actions. No remote service, publication,
RF hardware or key-distribution change is requested. Rotorcrypt remains
experimental and unauthenticated.

## Status

Implemented and automated acceptance completed. `make sync`, `make check` and
`make demo` passed; the default rotor/Morse demo recovered exact input without
diagnostics from a 105.66-second synthesized waveform. Focused backend tests cover
16 cipher/transport/mode/encoding round trips and failure cases, including abrupt
disconnect and same-session retry. Browser lifecycle tests cover readiness,
playback/capture isolation, tail flush, cleanup and stale callbacks. External
Chrome displayed the enabled control; that UI check did not activate hardware.

The checked criteria above describe software validation using real decoders and
stubbed audio devices. Measured physical acceptance of the single-tab workflow
remains pending; no room-acoustic or radio compatibility claim is made.
