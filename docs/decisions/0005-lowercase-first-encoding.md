# 0005: Optional lowercase-first encoding

Status: Superseded by [ADR 0006](0006-default-lowercase-first.md) for defaults and option naming; wire encoding retained.
Date: 2026-10-03

## Context

The maintainer requested reversible case inversion so lowercase prose can use
single rotor symbols, while decryption preserves the original capitalization.
The request includes all encryption/decryption tools and the demos. Converting
ciphertext in an audio transport cannot reduce encoding expansion that already
happened at encryption input.

## Options considered

- Uppercase normalization reduces rotor symbol count but loses original case.
- Changing the default codec silently would misinterpret existing raw recordings.
- An explicit reversible encoding preserves text exactly and keeps legacy defaults.

## Decision

Implement the maintainer's accepted lowercase-first option as
`--text-encoding ascii|lowercase-first`, defaulting to `ascii` in both cipher tools
and demos. ASCII case swapping is byte-local, reversible and length-preserving.
Rotorcrypt swaps before escape encoding and after escape decoding; its checked
CRC still covers the original user bytes. Sealcrypt swaps before AEAD encryption
and reverses only after authentication. It gains no size reduction because it
already handles both letter cases without escaping. Its primitives, key handling,
session salt generation and nonce rules remain unchanged.

Extend version-1 flags with rotor bit `0x02` and seal bit `0x04` to identify
lowercase-first, including end records. Existing flags and packet layouts remain
unchanged. Receiver selection must match. Seal's full-header associated data
authenticates its encoding flag. Older framed receivers reject the new flags.
Raw rotor retains its unframed stream and requires an explicit matching selection.

Route the option through shared Python factories and every demo cipher path,
including offline round trips, WAV imports and live streams. Transports continue
preserving ciphertext exactly. Plain text mode does not accept this cipher option.

## Consequences

Lowercase prose becomes smaller in rotorcrypt; uppercase prose can become larger.
Spaces retain their escape overhead. The 47-byte example in the protocol uses
61 raw symbols instead of 139 and still recovers exactly. This is a representation
choice, not compression for arbitrary input or a security improvement.

Both endpoints must select the same encoding. Framed mismatches fail before
plaintext release. Raw rotor has no encoding marker or integrity check and may
silently recover inverted case on a mismatch. Legacy messages retain `ascii`.

## Verification

Check all ASCII bytes, split escapes and arbitrary streaming chunks; retain
legacy wire vectors; verify framed encoding markers, mismatches, unknown flags
and authenticated flag tampering without plaintext release. Exercise both ciphers,
both modes and both audio transports through the real PCM decoders, plus browser
offline/upload/live routing. Run repository checks and the default demo. See the
[task criteria](../tasks/lowercase-first-encoding.md) and
[validation record](../VALIDATION.md).
