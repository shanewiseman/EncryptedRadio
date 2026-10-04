# sealcrypt: authenticated ASCII encryption

`sealcrypt` is a command-line replacement for `rotorcrypt` in text pipelines. It
uses the maintained `cryptography` implementation of ChaCha20-Poly1305, with
HKDF-SHA256 to derive independent session keys. Morse and other transports still
receive ASCII symbols. It is a separate, versioned protocol: both ends must use
`sealcrypt` and a new 256-bit key. Existing rotor ciphertext and rotor keys are not
compatible.

Checked mode is the default. See the shared
[raw and checked mode comparison](USAGE.md#raw-and-checked-modes)
for the differences in buffering, recovery and receive latency across both ciphers.

## Threat model

The new command protects plaintext confidentiality and authenticates each record
against changes by an attacker without the shared key. All headers and the chosen
public machine configuration are authenticated. A receiver never releases the
plaintext of a record with an invalid tag. The empty end record authenticates the
stream boundary; loss, reordering and truncation produce errors. Checked mode can
release intact later records after reporting lost data, so applications must check
exit status as well as read stdout. Previously released, verified records cannot be
retracted when a later failure is detected.

This is a new application protocol using established primitives, not an audited
communications system. Shared-key possession authenticates messages, not individual
identities. It has no key exchange, forward secrecy, durable replay protection,
traffic-analysis protection, delivery guarantee or defense against compromised
endpoints. Replaying a complete valid recording to a fresh receiver is possible.
The public session ID, record lengths, sequence numbers and timing are visible.
The bounded recent-session cache only handles repeats within a running receiver.

## Interface and compatibility

The `encrypt` and `decrypt` operations accept the same options as `rotorcrypt`:
`--machine`, `--key`, `--mode checked|raw`, `--uppercase-first`,
`--text-encoding lowercase-first|uppercase-first|ascii`,
`--text`, `--input`, `--block-size`
and `--idle-seconds`. Text and input-file options are mutually exclusive; omitted
input means an open streaming stdin. All 128 ASCII byte values, including NUL and
newlines, round-trip exactly. Non-ASCII plaintext is rejected. Stdout is payload
only, stderr is diagnostics, and available output is flushed. Broken pipes and
interrupts have controlled exits. Terminal line buffering still applies.

`lowercase-first` is the default. It swaps ASCII letter case before encryption
and reverses the swap only after record authentication succeeds. All original
bytes and capitalization are recovered. Use the same setting on both ends;
records carry an authenticated encoding flag and a mismatch is rejected. Older
receivers reject the new flag. Use `--uppercase-first` on both ends to select the
previous behavior; older default recordings require this flag at decryption.
`--text-encoding uppercase-first` is equivalent, and `ascii` remains an alias for
that choice. The shorthand and `--text-encoding` cannot be used together. Key
generation works without an encoding selection and rejects explicit encoding options.

Unlike rotorcrypt, sealcrypt does not escape individual ASCII bytes, so
lowercase-first **does not reduce its ciphertext length**. It is available for a
consistent cipher interface; it adds no security. Both transports carry its
ciphertext unchanged. See the [encoding comparison](USAGE.md#text-encoding).

`--machine` accepts the same public machine JSON, validates it, and binds its
canonical full SHA-256 digest into key derivation and authentication. Rotor wiring
is not used as an encryption primitive. Both ends must supply the same machine,
shared key, mode and text encoding. Public machine data supplies context, not a secret; the
random key supplies the secret.
`--key` uses the new key format below; rotor settings are deliberately rejected.

Checked mode buffers 128 plaintext bytes by default, emits a full block immediately,
flushes a partial block after five idle seconds or at EOF, and supports block sizes
1–256. `--idle-seconds` changes the checked encryption idle interval; it does not
time out decryption. It reports damaged/missing/repeated records
and can recover subsequent authenticated records. Silence never expires a partial
record. EOF emits a mandatory authenticated end record.

Raw mode flushes each available input chunk immediately, splitting it at the block
size. Input chunk boundaries depend on the pipe or file reads; a chunk is not
necessarily one typed character or one line. The raw receiver fails on the first
detected stream error. It still uses authenticated records and an end marker.
It cannot provide the rotor cipher's character-by-character
decryption latency: each record must arrive in full before any of its plaintext is
released. Small raw chunks also have greater Morse overhead. Neither mode emits
unauthenticated plaintext or falls back to rotor decryption.

## Key generation and commands

```sh
make sync
. .venv/bin/activate
sealcrypt keygen --key secrets/seal-key.json
set -o pipefail

sealcrypt encrypt --machine examples/machine.json --key secrets/seal-key.json \
  | morselink tx

morselink rx \
  | sealcrypt decrypt --machine examples/machine.json --key secrets/seal-key.json

# Raw streaming: pair the raw cipher and transport profiles.
sealcrypt encrypt --mode raw --machine examples/machine.json --key secrets/seal-key.json \
  | morselink tx --profile raw
morselink rx --profile raw \
  | sealcrypt decrypt --mode raw --machine examples/machine.json --key secrets/seal-key.json

# Offline files and WAV: no sound device required.
mkdir -p tmp
sealcrypt encrypt --machine examples/machine.json --key secrets/seal-key.json \
  --text 'Meet at 09:30!' | morselink tx --output-wav tmp/sealed.wav
morselink rx --input-wav tmp/sealed.wav \
  | sealcrypt decrypt --machine examples/machine.json --key secrets/seal-key.json
```

Share the key file separately over a trusted channel. Key generation uses the
operating system's random source, creates missing parent directories with mode
0700 and the key file with mode 0600, and refuses to overwrite an existing path.
It never prints key material to stdout or stderr. The file contains exactly
`version: 1`, `algorithm: "chacha20-poly1305"`, and `key_hex`: 64 hexadecimal digits
representing 32 random bytes. Passwords and rotor configurations are not keys.
Key files are UTF-8 JSON, bounded to 4,096 bytes; duplicate or unknown fields and
unsupported versions or algorithms are rejected. Key generation changes only
newly created directories and files, not permissions on existing parent directories.
Keep keys under ignored `secrets/`; copying a key file does not encrypt it at rest.

Both the browser and terminal `er-demo` can select `sealcrypt` with either audio
transport. For example:

```sh
er-demo roundtrip --cipher sealcrypt --transport audiolink --output-dir tmp/demo-sealed-afsk
er-demo roundtrip --cipher sealcrypt --transport morselink --key secrets/seal-key.json
```

Omitting `--key` in a seal demo generates an ephemeral random key held only in
memory. The browser also generates a fresh in-memory key and offers generation
and JSON import controls. Keys are not included in downloaded job artifacts and
are not stored in browser local storage. Use/import the same separately saved
key for external reception or later WAV decoding; the generated demo key does
not survive a server/browser restart as a durable key store. Cipher selection
does not select the text encoding; choose that separately at both endpoints.

Substitute `audiolink` for `morselink` at both ends of the examples above to use
packet audio. See [AUDIOLINK.md](AUDIOLINK.md) for its separate wire format and
voice-band assumptions. The transport does not receive the shared encryption key.

## Protocol v1

Each record is `VVV(` + canonical unpadded uppercase Base32 + `)`. The training
prefix and alphabet already work with `morselink`; a new opening delimiter permits
checked reception to resynchronize. The binary header uses network byte order:

| Offset | Bytes | Field |
| --- | --- | --- |
| 0 | 2 | Magic `SC` |
| 2 | 1 | Version 1 |
| 3 | 1 | Flags: bit `0x01` is end, `0x02` is raw mode, `0x04` is lowercase-first encoding; all other bits are rejected |
| 4 | 32 | Random session ID and HKDF salt |
| 36 | 4 | Sequence number, initially zero |
| 40 | 2 | Plaintext byte count: data 1–256, end zero |
| 42 | 8 | First eight bytes of the public machine's SHA-256 digest |
| 50 | variable | Ciphertext with a full 16-byte authentication tag |

The header is `struct.Struct("!2sBB32sIH8s")`. The complete packet is at most
322 bytes, or 516 Base32 characters (521 symbols with the preamble and delimiters).
There is no escape encoding, plaintext CRC, or secret-derived public fingerprint.
Uppercase-first encrypts original ASCII bytes directly; default lowercase-first
swaps ASCII letter case first without changing byte count. Flags `0`–`3` retain their original
meanings; lowercase-first uses checked data/end `4`/`5` and raw data/end `6`/`7`.
This extends the version-1 flags without changing the packet layout.

Canonical machine JSON uses the validated version-1 fields, sorted keys, compact
separators and ASCII escaping, as in the [rotor protocol](PROTOCOL.md). Its full
32-byte SHA-256 digest is used even though only eight bytes appear in the header.

For each new encoder, draw a fresh 32-byte session ID. Derive the session key with
HKDF-SHA256 using the master key as input key material, session ID as salt, length
32, and the following info bytes:

```text
ASCII("EncryptedRadio/sealcrypt/v1") || 0x00 || mode_byte || machine_digest[32]
```

The mode byte is 0 for checked, 1 for raw. Each record's 12-byte nonce is eight zero
bytes followed by its four-byte sequence. Associated data is the exact 50-byte
header followed by the full machine digest, authenticating the encoding flag as
well as the mode and other fields. Sequence numbers never wrap: the last
number `0xFFFFFFFF` is reserved for an end record. A new process uses a fresh random
session salt; no user-supplied nonce/session override is exposed. Security depends
on avoiding session-salt repetition under the same master key and context.

Only authenticated records can change receiver session/sequence state. Bounds,
header fields, canonical Base32, tag and plaintext ASCII are validated before
release. Checked reception suppresses duplicate/old records, reports sequence gaps,
and resumes with later intact records. A new session before the previous end
record reports an incomplete previous session; the latest 64 superseded session
IDs are retained to suppress delayed records. Silence preserves partial records.
Invalid symbols, oversized bodies, replaced partial frames, trailing truncation
and missing end records produce errors. Raw reception terminates at the first
such error instead of attempting recovery.

Checked errors are bounded to 128 diagnostics plus an omission notice. An error
remains reflected in the exit status even after later recovery. The library's
`complete` attribute records receipt of an end marker without trailing truncation;
it does not clear prior `errors`, which callers must inspect as well.

Exit codes match the existing command: 0 success, 1 stream integrity failure,
2 configuration/input failure, 130 interruption, 141 broken output pipe.

## References

- [ChaCha20-Poly1305 specification, RFC 8439](https://www.rfc-editor.org/rfc/rfc8439)
- [cryptography AEAD API](https://cryptography.io/en/stable/hazmat/primitives/aead/)
- [cryptography HKDF API](https://cryptography.io/en/stable/hazmat/primitives/key-derivation-functions/#hkdf)
