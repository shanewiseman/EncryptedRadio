# Changelog

Record notable user-visible changes here. Keep unreleased work under **Unreleased**; add a version and release date only when a release is actually made. Do not list planned features as completed work.

## Unreleased

### Added

- Single-tab **Acoustic round trip** in the browser demo: arm the microphone,
  inspect transmission duration, play through speakers and automatically finish
  reception with recovered-text comparison and decoder diagnostics. Both ciphers,
  both transports and checked/raw/text modes use the existing Python pipeline;
  Stop releases both audio directions.
- Lossless lowercase-first encoding across both cipher tools and terminal
  demos, with a matching browser selector for round trips, WAV decoding and live
  operations. Exact original case is restored; lowercase rotor prose uses fewer
  symbols. Framed encoding mismatches fail before releasing the affected plaintext.
  Sealcrypt supports the option consistently without changing ciphertext length.
- `rotorcrypt`, a configurable 49-symbol Enigma-style rotor cipher, lossless ASCII codec, raw
  streaming and checked blocks with corruption/loss reporting and recovery.
- `sealcrypt`, a ChaCha20-Poly1305 replacement CLI with the same ASCII/file/stdin
  interface, raw/checked streaming modes, authenticated records, private key
  generation and Morse compatibility.
- `morselink`, a replaceable Morse transport with WAV and optional PortAudio I/O, automatic
  frequency/timing acquisition, three profiles and bounded queues.
- `audiolink`, a packet AFSK transport with 1,200/2,200 Hz tones, error correction,
  checked/raw/text profiles, streaming text pipes, WAV and live audio.
- `er-demo`, terminal/local browser demonstrations selecting either cipher and
  either transport through the real PCM decoder, including seeded noise and
  removed-audio-block scenarios, in-memory seal keys and configuration import.
- Locked dependencies, application/browser tests, protocol and operation guides.
- Initial repository guidance for prompt-driven development, contribution review, security reporting, and project decisions.
- Repository checks and declarative GitHub configuration support.

### Changed

- Lowercase-first is now the default in cipher APIs, CLIs and all demo paths.
  `--uppercase-first` selects the previous encoding at both endpoints; the equivalent
  `--text-encoding uppercase-first` and legacy `ascii` alias are supported. Older
  default recordings need the explicit override when decoding. Plain text and
  seal key generation keep their existing behavior.
- Updated usage, architecture, security guidance and contributor templates for both
  ciphers, their distinct raw/checked behavior, separate key formats, and the scope
  of terminal/browser demonstrations and validation evidence.
- Documented the provisional voice-band target, packet transport boundaries and
  separation between synthetic loopback results and physical radio acceptance.

This is unreleased experimental software. Licensing remains undecided.
