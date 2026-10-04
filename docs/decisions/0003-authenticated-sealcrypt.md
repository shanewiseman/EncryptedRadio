# 0003: Authenticated replacement cipher command

Status: Accepted
Date: 2026-10-03

## Context

After discussing modern authenticated encryption, the maintainer requested another
script that can replace rotorcrypt while keeping its input/output and runtime
interfaces. This authorizes a separate implementation without replacing the rotor
demonstration or changing the Morse transport.

## Decision

Name the new command `sealcrypt`. Use `cryptography`'s ChaCha20-Poly1305 with a random
256-bit shared key. Generate a fresh 256-bit session salt for every encoder and
derive a session key with HKDF-SHA256 bound to the mode and full public machine
digest. Use a unique sequential nonce per record with no counter wrapping. Protect
all header fields and the full context digest with associated data.

Retain encrypt/decrypt, machine/key paths, raw/checked modes, text/file/stdin input,
bounded block size, idle flushing and error-status conventions. The machine JSON
is authenticated context, not rotor key material. Require a separate key format
and add exclusive private-file key generation. Keep ASCII output in the existing
Morse-safe `VVV(Base32)` delimiters with a distinct magic/version protocol.

Authenticate records in both modes. Checked mode allows recovery after loss;
raw mode emits immediately on each available input chunk and fails on detected
stream errors. Both withhold record plaintext until its tag verifies and require
an authenticated end marker at finite EOF.

## Consequences

The pipeline and runtime controls remain familiar, but ciphertext and key files
are not interchangeable with rotorcrypt. Raw decryption has record-sized latency
and overhead because immediately releasing unauthenticated characters would defeat
the purpose of the replacement. Random session salts avoid requiring persistent
nonce-counter storage; they must never be overridden or reused in production.

Shared-key authentication is not individual sender identity. There is no durable
replay protection, key exchange, forward secrecy or delivery guarantee. The new
application protocol needs independent review before production security claims.

## Verification

Independent known-answer and protocol tests cover authentication, context binding,
all ASCII bytes, arbitrary chunks, corruption, loss/reordering, end markers, bounds
and exhaustion. Subprocess tests exercise key permissions, no-overwrite behavior,
idle/raw streaming and controlled exits. A real PCM/Morse round trip verifies that
the replacement needs no change to the audio transport. Existing tests remain in
`make check`. See [protocol](../SEALCRYPT.md) and [security policy](../../SECURITY.md).
