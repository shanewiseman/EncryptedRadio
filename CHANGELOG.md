# Changelog

Record notable user-visible changes here. Keep unreleased work under **Unreleased**; add a version and release date only when a release is actually made. Do not list planned features as completed work.

## Unreleased

### Added

- `rotorcrypt`, a configurable 49-symbol Enigma-style rotor cipher, lossless ASCII codec, raw
  streaming and checked blocks with corruption/loss reporting and recovery.
- `sealcrypt`, a ChaCha20-Poly1305 replacement CLI with the same ASCII/file/stdin
  interface, raw/checked streaming modes, authenticated records, private key
  generation and Morse compatibility.
- `morselink`, a replaceable Morse transport with WAV and optional PortAudio I/O, automatic
  frequency/timing acquisition, three profiles and bounded queues.
- `er-demo`, terminal/local browser demonstrations through rotorcrypt and the real PCM decoder,
  including seeded noise and removed-audio-block scenarios.
- Locked dependencies, application/browser tests, protocol and operation guides.
- Initial repository guidance for prompt-driven development, contribution review, security reporting, and project decisions.
- Repository checks and declarative GitHub configuration support.

### Changed

- Updated usage, architecture, security guidance and contributor templates for both
  ciphers, their distinct raw/checked behavior, separate key formats, and the scope
  of terminal/browser demonstrations and validation evidence.

This is unreleased experimental software. Licensing remains undecided.
