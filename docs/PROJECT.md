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
- `er-demo`: actual cipher → PCM → DSP → cipher round trips, including noise and
  removed-audio-block fixtures. Local aiohttp browser UI uses the same rotor code;
  `sealcrypt` is available through its separate CLI and shared Python module.
- Bounded buffers, explicit discontinuity reporting, finite-input integrity status,
  deterministic automated tests, lockfile installation and CI.

## Acceptance boundaries

Tests verify synthetic signals, format errors, streaming behavior, resource limits
and local web requests. They do not establish real speaker/microphone, radio or
human-keying compatibility. Physical acceptance procedures and current evidence
are in [VALIDATION.md](VALIDATION.md).

Enigma-style encryption is deliberately educational. `rotorcrypt` has no
authentication or modern confidentiality guarantee; a fresh rotor session ID does
not make that cipher secure. `sealcrypt` provides authenticated encryption through
established primitives, but its application protocol is unaudited and supplies no
identity system, key exchange, forward secrecy or durable replay protection. See
[SEALCRYPT.md](SEALCRYPT.md) and [SECURITY.md](../SECURITY.md).

The suite has no retransmission, acknowledgement, FEC, station separation, RF
hardware control or automatic repair of missing content. Checked reception reports
missing records while allowing recovery of intact later records; callers must
inspect finite-input exit status as well as output. Raw `sealcrypt` reception stops
on detected corruption or ordering errors; raw `rotorcrypt` has no equivalent
integrity guarantee. The [mode comparison](USAGE.md#raw-and-checked-modes) explains
latency and recovery for both commands. Changing modes does not add authentication
to the rotor cipher or remove it from `sealcrypt`.

## Open decisions

Licensing remains undecided. Real deployment, RF hardware, bands, operating rules,
identity/key distribution, protocol security review and release support require
separate requirements. Authenticated CLI encryption is implemented; adding it to
the browser's rotor interface is outside the current change. The audio demo does
not choose deployment policies.

Future changes must preserve the transport's ASCII interface or explicitly version
it. Keep accepted requirements, evidence and limitations in version control rather
than relying on chat history. Start substantial work from [TASK_TEMPLATE.md](TASK_TEMPLATE.md).
