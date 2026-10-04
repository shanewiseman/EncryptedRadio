# Project brief

EncryptedRadio is developed through human-directed LLM/AI prompts. The accepted
initial implementation is a Linux-first Python 3.12+ suite with terminal and local
browser demonstrations. Maintainer: [@shanewiseman](https://github.com/shanewiseman).
Integration branch: protected `master`; rebase integration only.

## Implemented scope

- `rotorcrypt`: configurable 49-symbol Enigma-style cipher; reversible escaping
  preserves all 128 ASCII bytes. Raw and independently framed checked modes.
- `morselink`: half-duplex Morse transmission/reception, streaming text pipes,
  mono WAV files and optional Linux PortAudio devices. One foreground tone at
  400–1200 Hz and 8–30 WPM, with manual overrides and automatic acquisition.
- `er-demo`: actual cipher → PCM → DSP → cipher round trips, including noise and
  removed-audio-block fixtures. Local aiohttp browser UI uses the same code.
- Bounded buffers, explicit discontinuity reporting, finite-input integrity status,
  deterministic automated tests, lockfile installation and CI.

## Acceptance boundaries

Tests verify synthetic signals, format errors, streaming behavior, resource limits
and local web requests. They do not establish real speaker/microphone, radio or
human-keying compatibility. Physical acceptance procedures and current evidence
are in [VALIDATION.md](VALIDATION.md).

Enigma-style encryption is deliberately educational. There is no authentication,
modern confidentiality guarantee, retransmission, acknowledgement, FEC, station
separation, RF hardware control or automatic repair of missing content. A fresh
session ID limits accidental block-state reuse; it does not make the cipher secure.

## Open decisions

Licensing remains undecided. Real deployment, RF hardware, bands, operating rules,
identity/key distribution, authenticated cryptography and release support require
separate requirements. The audio demo does not choose those policies.

Future changes must preserve the transport's ASCII interface or explicitly version
it. Keep accepted requirements, evidence and limitations in version control rather
than relying on chat history. Start substantial work from [TASK_TEMPLATE.md](TASK_TEMPLATE.md).
