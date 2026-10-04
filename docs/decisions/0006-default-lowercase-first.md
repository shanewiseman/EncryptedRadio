# 0006: Lowercase-first by default

Status: Accepted
Date: 2026-10-03

## Context

After accepting the reversible encoding in [ADR 0005](0005-lowercase-first-encoding.md),
the maintainer requested lowercase-first as the default and a flag to select
uppercase-first. This explicitly changes the previous compatibility default
across encryption and decryption tools, including terminal and browser demos.

## Decision

Default cipher libraries, CLIs and demo cipher paths to `lowercase-first`.
Provide the CLI shorthand `--uppercase-first` and the equivalent
`--text-encoding uppercase-first` at both endpoints. Keep `ascii` as a legacy
alias for uppercase-first and continue accepting explicit `lowercase-first`.
Normalize aliases to the canonical names. Reject conflicting CLI options.

The browser initially selects lowercase-first and exposes uppercase-first as the
legacy choice. All omitted encoding settings in offline, WAV and live cipher
requests use the new default. Unencrypted text mode retains its original
uppercase/whitespace normalization; its absence of a cipher does not become an
error merely because the cipher default changed. Returning from text mode
restores the previous cipher encoding selection. Seal key generation remains
independent of encoding and rejects explicitly supplied encoding options.

Retain both existing wire encodings and their flag meanings, CRC/authentication
coverage, rotor math, salts, nonces and transport behavior. This changes which
encoding is chosen when the caller omits a setting, not either encoding's format.

## Consequences

New default rotor encryption uses 61 raw symbols for the 47-byte example in the
protocol; uppercase-first uses 139. Both recover the original bytes and case.
Sealcrypt shares the interface without a size reduction.

Recordings made with the previous default require `--uppercase-first` when
decrypting. Framed mismatches are rejected, including seal's authenticated raw
records. Raw rotor has no marker or integrity check and can silently invert case
if the wrong selection is used. Both endpoints must choose the same encoding;
there is no heuristic auto-detection or fallback.

## Verification

Keep original uppercase-first wire vectors as explicit compatibility fixtures.
Verify default, explicit lowercase-first, uppercase-first and `ascii` alias
behavior through APIs, both CLI directions and demos. Check key generation,
plain text mode, option conflicts, omitted browser settings, and encoding mismatch
failures. Run repository checks, the default demo and both cipher/mode/transport
combinations through synthesized PCM. See [validation](../VALIDATION.md).
