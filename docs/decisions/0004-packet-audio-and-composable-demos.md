# 0004: Packet audio and composable demonstrations

Status: Accepted
Date: 2026-10-03

## Context

The maintainer requested a more efficient replacement for Morse while preserving
its text-pipe and audio interfaces, then authorized implementation and independent
cipher/transport selection in the web demonstration. A conventional analog
handheld voice-audio path is the target; the GXT3000 is a capability reference,
not a selected deployment device. Its documentation does not establish a measured
audio response for this modem.

An earlier ggwave experiment established clean full-band software loopback gains.
Its audible profile extends beyond the provisional 300–3,000 Hz channel target,
so those gains cannot establish acceptance for the narrower replacement.

## Decision

Implement `audiolink` with 1,200-bit/s continuous-phase AFSK using 1,200/2,200 Hz
tones. Preserve `tx`, `rx`, device enumeration/selection, streaming stdin/stdout,
WAV input/output, checked/raw/text profiles and half-duplex live operation. Add
packet integrity, sequence tracking, an explicit end marker and bounded forward
error correction. Keep its packet protocol separate from the cipher protocols;
transport processing receives neither private keys nor plaintext knowledge.

Let `er-demo` and the browser choose `rotorcrypt` or `sealcrypt` independently of
`morselink` or `audiolink`. Use shared Python factories and implementations;
JavaScript does not duplicate cipher or DSP algorithms. Preserve rotor/Morse
defaults. Generate seal demo keys in memory unless explicitly supplied, and keep
keys out of report artifacts and persistent browser storage.

The maintainer accepted implementation of the replacement and expanded demos.
The modem's concrete framing and error-correction choices implement that scope;
[audiolink's guide](../AUDIOLINK.md) records their versioned format and limits.

## Consequences

Matching audio transports are required at both ends; Morse and packet AFSK are
not wire-compatible. Application payloads remain ASCII and both existing ciphers
continue to own cryptographic framing and recovery. Error correction and CRCs do
not authenticate the channel. Raw transport still uses packets and stops on
detected errors; checked mode reports loss and allows later cipher recovery.

Coding, packet headers, end signaling and burst guards reduce useful throughput
below the gross bit rate. Small streaming chunks cost proportionally more than
full packets. The fixed modem has separate controls from Morse frequency/WPM.
No acknowledgement, retransmission, vendor PTT or radio firmware integration is
introduced. The protocol and DSP are experimental; simulated acceptance is not
hardware or radio interoperability evidence.

## Verification

Run exact PCM loopbacks and all four cipher/transport combinations. Cover packet
corruption/loss/reordering/end markers, arbitrary chunks, bounded buffering,
44.1/48 kHz, silence, declared voice-band filtering and noise, and sample-clock
mismatch. Measure waveform duration with all coding and acquisition overhead.
Exercise browser configuration, key import/generation, live PCM credit limits,
cancellation and cleanup through shared backends. Keep physical speaker/microphone
and radio acceptance separate in [VALIDATION.md](../VALIDATION.md).

## References

- [Audio-channel target and packet protocol](../AUDIOLINK.md)
- [Architecture](../ARCHITECTURE.md)
- [Authenticated cipher decision](0003-authenticated-sealcrypt.md)
- [Security policy](../../SECURITY.md)
