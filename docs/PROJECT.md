# Project brief

EncryptedRadio is developed through human-directed LLM/AI prompts. The accepted
initial implementation is a Linux-first Python 3.12+ suite with terminal and local
browser demonstrations. Maintainer: [@shanewiseman](https://github.com/shanewiseman).
Integration branch: protected `master`; rebase integration only.

## Implemented scope

- `rotorcrypt`: configurable 49-symbol Enigma-style cipher; reversible escaping
  preserves all 128 ASCII bytes. Raw mode maintains continuous rotor state;
  independently framed checked mode detects accidental damage and permits recovery.
- `sealcrypt`: an authenticated alternative with the same text/file/stdin and
  streaming CLI options. ChaCha20-Poly1305 protects ASCII records, HKDF-SHA256
  derives session keys, and local key generation creates random 256-bit keys.
  Both raw and checked modes authenticate complete records before plaintext release.
  Both endpoints use its distinct protocol, matching mode and private key format.
- `morselink`: half-duplex Morse transmission/reception, streaming text pipes,
  mono WAV files and optional Linux PortAudio devices. One foreground tone at
  400–1200 Hz and 8–30 WPM, with manual overrides and automatic acquisition.
- `audiolink`: a drop-in ASCII transport using packet AFSK at 1,200 bits/s and
  1,200/2,200 Hz tones, with framing, forward error correction, integrity checks,
  sequence tracking, streaming input and WAV/live audio adapters.
- `er-demo`: actual cipher → PCM → DSP → cipher round trips, including noise and
  removed-audio-block fixtures. The terminal and local aiohttp browser UI select
  either cipher and either transport independently and share the Python
  implementations. Seal demo keys are generated in memory unless supplied.
- A finite browser **Acoustic round trip** arms microphone capture before speaker
  playback in one tab, finishes after playback and a capture tail, and compares
  actual received plaintext with the original input. Both ciphers, both transports
  and checked/raw/text modes use the shared Python path. Plain text compares after
  transport normalization. See [task acceptance](tasks/acoustic-round-trip.md).
- Bounded buffers, explicit discontinuity reporting, finite-input integrity status,
  deterministic automated tests, lockfile installation and CI.
- Lowercase-first encoding by default in both cipher CLIs and APIs, terminal demos
  and browser offline/upload/live paths. It preserves exact case and all ASCII
  bytes and reduces rotor ciphertext for lowercase prose. `--uppercase-first`
  selects the previous encoding; older default recordings require this override.
  Sealcrypt supports the setting without a size reduction. See the
  [task acceptance criteria](tasks/lowercase-first-encoding.md) and
  [default-encoding decision](decisions/0006-default-lowercase-first.md).

## Acceptance boundaries

Tests verify synthetic signals, format errors, streaming behavior, resource limits
and local web requests. An informal user trial exercised speaker transmission and
microphone reception in two browser tabs; no measured physical acceptance results
were recorded. Automated tests do not establish speaker/microphone, radio or
human-keying compatibility. Physical acceptance procedures and current evidence
are in [VALIDATION.md](VALIDATION.md).

Enigma-style encryption is deliberately educational. `rotorcrypt` has no
authentication or modern confidentiality guarantee; a fresh rotor session ID does
not make that cipher secure. `sealcrypt` provides authenticated encryption through
established primitives, but its application protocol is unaudited and supplies no
identity system, key exchange, forward secrecy or durable replay protection. See
[SEALCRYPT.md](SEALCRYPT.md) and [SECURITY.md](../SECURITY.md).

The suite has no retransmission, acknowledgement, station separation, RF hardware
control or reconstruction of missing cipher records. `audiolink` adds bounded
forward error correction at the transport layer; errors beyond its correction
capability are reported. Checked reception reports
missing records while allowing recovery of intact later records; callers must
inspect finite-input exit status as well as output. Raw `sealcrypt` reception stops
on detected corruption or ordering errors; raw `rotorcrypt` has no equivalent
integrity guarantee. The [mode comparison](USAGE.md#raw-and-checked-modes) explains
latency and recovery for both commands. Changing modes does not add authentication
to the rotor cipher or remove it from `sealcrypt`.

## Audio-channel target

`audiolink` targets a conventional handheld analog voice-radio audio path, using
GXT3000-class capabilities as an engineering reference rather than a deployment
choice. Its [design and protocol guide](AUDIOLINK.md) distinguishes documented
reference capabilities from provisional channel assumptions. A nominal
300–3,000 Hz channel is a test model, not a measured GXT3000 specification.
Software validation and its limits are recorded in [VALIDATION.md](VALIDATION.md).

## Open decisions

Licensing remains undecided. Real deployment, RF hardware, bands, operating rules,
identity/key distribution, protocol security review and release support require
separate requirements. The browser supports both ciphers and transports but is a
trusted local demonstration, not a multi-user service. The audio demo does not
choose deployment policies.

Future changes must preserve the transport's ASCII interface or explicitly version
it. Keep accepted requirements, evidence and limitations in version control rather
than relying on chat history. Start substantial work from [TASK_TEMPLATE.md](TASK_TEMPLATE.md).
