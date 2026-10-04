# 0002: Rotor cipher, replaceable Morse transport, and working demos

Status: Accepted
Date: 2026-10-03

## Context

The repository owner requested two composable applications: an Enigma-style text transform configured by rotor and plugboard files, and a half-duplex sound-card/microphone Morse adapter. Both must support batch input and continuous pipes. The transport must remain replaceable. The owner then requested working terminal and browser demonstrations and explicitly approved implementation of the resulting plan.

The intended product is a Linux-first experimental application. It must preserve all ASCII input without silently losing characters unsupported by ordinary Morse. The accepted cipher is educational and is not a modern security design.

## Options considered

- A single application coupling encryption, audio devices, and presentation would simplify the first UI but impede shell composition and replacement transports.
- Independent cipher and transport commands with shared libraries make their contracts testable and allow offline demonstrations and different future physical encodings.
- Restricting plaintext to uppercase Morse symbols would simplify rotor wiring but violate exact ASCII preservation. Escaping unsupported bytes adds overhead while preserving the requested input domain.
- Raw continuous rotors minimize framing latency but lose alignment after dropped symbols. Independent checked blocks add substantial Morse airtime while making later intact blocks recoverable.

## Decision

Implement the owner's accepted plan with Python 3.12+, `src/encrypted_radio`, versioned JSON configuration, `pyproject.toml`, and a committed `uv.lock`. Provide `rotorcrypt`, `morselink`, and `er-demo` commands.

Use the 49 ordinary Morse-compatible ASCII symbols for rotors, with `+HH` escapes preserving all 128 ASCII bytes. Select three to eight rotors with positions, ring offsets, and 10–16 disjoint plugboard pairs. Specify simultaneous notch evaluation and a reciprocal odd-length reflector with one fixed point. Bundle eight public demonstration rotors and a clearly public example key.

Keep framing in the cipher layer. Default to independent checked blocks with CRC32 error detection, Base32 envelopes, explicit end markers, bounded parsing, sequence-loss reporting, and deterministic per-block starting offsets. Offer raw streaming for immediate symbol output. Neither mode claims modern cryptographic security or authentication.

Use NumPy/SciPy for shared WAV/live signal processing and sounddevice/PortAudio for Linux audio. The initial receiver targets one foreground Morse signal in the documented frequency/speed envelope, with manual overrides and automatic acquisition. Ordinary unencrypted Morse is a separate text profile.

Demonstrate the actual plaintext → cipher → PCM/WAV → audio decoder → plaintext path. Terminal scenarios include clean, noisy, and lost-block reception. The local aiohttp browser demo uses the same Python core, standard browser audio APIs, and static HTML/CSS/JavaScript without a frontend build system. Browser code must not substitute a separate cipher or predetermined receive results.

## Consequences

- Shell pipelines and the symbol-stream contract allow a different transport without changing the cipher engine.
- ASCII escaping, framing, and Base32 significantly increase transmission time. Offline demonstrations run faster than real time; audible playback still takes its actual duration.
- Partial or damaged checked sessions can release earlier verified blocks and later recovered blocks while reporting failure. Consumers must inspect diagnostics and exit status; missing content is not reconstructed.
- Public examples make demonstrations reproducible and provide no secrecy. Private key lifecycle and adversarial channel security remain unsolved product requirements for any future secure system.
- Browser execution is local and trusted. Loopback/origin restrictions, bounded uploads/queues, explicit microphone permission, and cleanup limit exposure without turning the demo into an authenticated server.
- Tests can establish codec/protocol behavior and synthetic DSP performance. Physical speaker/microphone reception and human keying require separately reported evidence.
- RF hardware control, acknowledgements, retransmission, error-correcting codes, multiple simultaneous stations, and remote browser hosting are outside this release. Licensing remains undecided.

## Verification

Require meaningful automated coverage of all ASCII bytes, independently derived rotor behavior, arbitrary stream boundaries, configuration validation, checked-frame corruption/loss/reordering, sequence bounds, finite-input errors, all Morse symbols, signal/noise fixtures, subprocess pipes, demo artifacts, and browser operations. Extend the existing `make check` workflow without weakening repository protections.

Record actual outcomes and remaining gaps in [VALIDATION.md](../VALIDATION.md). A simulated test must not be described as a live hardware or real human-keying result.

## References

- [Project brief](../PROJECT.md)
- [Architecture](../ARCHITECTURE.md)
- [Protocol](../PROTOCOL.md)
- [Usage](../USAGE.md)
- [Security policy](../../SECURITY.md)
