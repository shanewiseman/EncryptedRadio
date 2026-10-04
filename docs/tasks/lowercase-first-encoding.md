# Lowercase-first encoding task

## Objective

Make lowercase letters the compact rotor representation without losing original
capitalization, and make this the default consistently in all cipher tools and demos.

## Context

The original ASCII codec escapes lowercase letters and spaces into three symbols.
The example `This message is encrypted using wwii technology` is 47 bytes but
requires 139 raw rotor symbols. The accepted reversible case inversion should
reduce it to 61 symbols. The maintainer subsequently requested this as the default,
with an uppercase-first override. See [ADR 0006](../decisions/0006-default-lowercase-first.md).

## Scope

- Both cipher libraries and encrypt/decrypt CLIs; terminal and browser demos.
- Checked/raw operation, text/file/stdin, streaming chunks, WAV imports and live PCM.
- Both audio transports remain exact ciphertext carriers.
- Preserve both wire encodings through explicit selection, queues, framing bounds
  and security rules; change the omitted cipher selection to lowercase-first.
- No lossy normalization, new cryptographic primitives, dependency changes,
  publishing, hardware testing or unrelated transport work.

## Acceptance criteria

- Default `lowercase-first` saves rotor symbols for lowercase prose
  and round-trips every ASCII value, including capitalization and controls.
- `--uppercase-first` and `--text-encoding uppercase-first` retain legacy wire
  vectors and decoding; the existing explicit `ascii` alias still works.
- Both cipher directions default to lowercase-first in libraries, CLIs and all
  demo paths. Conflicting CLI options are rejected.
- Framed streams identify the encoding and reject mismatches before release;
  raw rotor's undetectable mismatch limitation is documented.
- Seal authentication covers encoding flags and releases only verified plaintext;
  the interface clearly explains that this cipher gains no size reduction.
- Every demo cipher path passes the setting to shared Python, including live
  preparation, appended input, reception and uploaded WAVs. Plain text mode
  rejects explicit lowercase-first but still works when encoding is omitted.
- Seal key generation continues to work without cipher options. Plain text mode
  preserves its transport behavior and the browser restores the cipher selection
  when returning from text mode.
- Documentation describes both endpoint settings, compatibility and measured limits.

## Verification

Run `make sync`, `make check` and `make demo`, plus lowercase-first PCM round trips
for both ciphers, modes and transports. Tests must cover all ASCII bytes and chunk
boundaries, original-case CRC validation, encoding mismatch and flag tampering,
end records, legacy compatibility and CLI/browser propagation. Record actual
results in [VALIDATION.md](../VALIDATION.md); synthetic PCM and mocked browser/device
tests do not establish physical radio or microphone compatibility.

## Security and external effects

Use public rotor configurations and synthetic test keys only. Keep seal session
salts random, sequence nonces unique, all header context authenticated and plaintext
withheld until verification. Encoding is not a security improvement. No external
publication or key sharing is requested.

## Completion report

Report the available setting, symbol-count improvement, actual checks and remaining
compatibility limits. Preserve existing unrelated working-tree changes.

The initial optional-encoding implementation passed `make sync`, all 156 tests and hygiene in `make check`,
the default `make demo`, eight installed CLI/WAV combinations and a local browser
round trip passed. See [the validation record](../VALIDATION.md) for measured
symbol counts and the limits of synthetic audio evidence. The default change
subsequently passed all 162 tests and hygiene, the default demo, 16 installed
CLI/WAV combinations and browser round trips using both encoding choices.
