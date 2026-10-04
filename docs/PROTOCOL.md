# rotorcrypt cipher and transport protocol, version 1

This document specifies the implemented experimental rotor transform and checked symbol stream. It is an interoperability description, not a modern cryptographic security claim. Read the [security policy](../SECURITY.md) before using private data.

This specification applies to `rotorcrypt`. The authenticated replacement has its
own [sealcrypt protocol](SEALCRYPT.md), with different keys and packets even though
both commands share CLI options and Morse-compatible framing. Its raw mode also
uses authenticated records; the continuous rotor transform described here does
not apply to it. See the [mode comparison](USAGE.md#raw-and-checked-modes).

## ASCII and symbol alphabet

The rotor alphabet has 49 positions, numbered from zero in this exact order:

```text
ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,:?'/-()"=+@
```

These are ordinary ASCII characters represented by the project's international Morse table. Prosigns, accented characters, and whitespace are not rotor symbols. The cipher preserves all 128 ASCII byte values by escaping before encryption:

- Alphabet members other than `+` pass through unchanged.
- Every other ASCII byte, including literal `+`, becomes `+HH`, where `HH` is two uppercase hexadecimal digits.
- Non-ASCII input is rejected. Decryption rejects incomplete escapes, lowercase/non-hexadecimal escape digits, and decoded values above 127.

For example, the bytes `a`, space, `+`, and LF become `+61+20+2B+0A`. The encrypted output always consists of rotor alphabet characters. Whitespace is encoded explicitly, so a pause in transmission does not create plaintext spaces.

## Machine and key configuration

Configuration files are UTF-8 JSON, bounded to 1 MiB per file. Version 1 requires exactly the fields below; unknown fields and unsupported versions are rejected. JSON booleans are not accepted as indices or versions.

The [public machine example](../examples/machine.json) is also bundled as a package resource. Its fields are:

| Field | Meaning and validation |
| --- | --- |
| `version` | Integer `1`. |
| `alphabet` | The exact 49-character string above. |
| `rotors` | An object mapping 3–256 unique names to rotor definitions. Names contain 1–64 ASCII characters. The supplied catalog has eight demonstration rotors, `I` through `VIII`. |
| `rotors[name].wiring` | A 49-character permutation. Character at index `i` is the output for input index `i` at zero electrical offset. |
| `rotors[name].notches` | A nonempty list of distinct integer display positions from 0 through 48. |
| `reflector` | A 49-character permutation, interpreted like rotor wiring, which must be reciprocal and have exactly one fixed point. |

A reciprocal reflector maps each paired character back to its partner. Because the alphabet has odd size, one character must map to itself; this implementation requires exactly one such character.

`sealcrypt` accepts this same public machine schema to bind an authenticated
configuration context. It does not use these rotors or reflector to encrypt.

The [public example rotor key](../examples/example-key.json) selects three rotors and twelve plugboard cables. Its fields are:

| Field | Meaning and validation |
| --- | --- |
| `version` | Integer `1`. |
| `rotors` | An ordered list of 3–8 distinct names from the machine catalog, leftmost rotor first. |
| `positions` | One initial displayed position per selected rotor, each an integer from 0 through 48. |
| `rings` | One ring offset per selected rotor, each an integer from 0 through 48. |
| `plugboard` | 10–16 two-character strings, with both characters in the alphabet. Characters must be distinct across the entire list, so self-pairs and shared sockets are invalid. |

One plugboard entry is one cable connecting two characters. Unconnected characters map to themselves. These public examples are demonstration data, not private keys. Put private configurations under the ignored `secrets/` directory and protect them with appropriate filesystem permissions. Ignoring a path does not encrypt its contents.

This private rotor configuration cannot be used as a `sealcrypt` key. Generate that
command's random shared key using the [sealcrypt key procedure](SEALCRYPT.md#key-generation-and-commands).

## Rotor transform and raw mode

The selected stack is ordered left-to-right. For every escaped input symbol, inspect all displayed positions **before** advancing any rotor:

1. Mark the rightmost rotor to advance.
2. Each rotor other than the leftmost, when currently at one of its notches, marks itself and its left neighbor to advance.
3. Advance every marked rotor once, modulo 49. A rotor marked twice still advances only once.

This preserves the middle-rotor double-step behavior. Ring settings affect the electrical transform; notch comparisons use displayed positions without a ring adjustment.

After stepping, pass the symbol through the plugboard, each rotor from right to left, the reflector, each inverse rotor from left to right, and the plugboard again. For rotor permutation `w`, displayed position `p`, and ring `r`, the forward electrical transform is:

```text
output = (w[(input + p - r) mod 49] - p + r) mod 49
```

The reverse traversal uses the inverse permutation in the same formula. The transform is reciprocal: the same starting state transforms ciphertext symbols back into escaped plaintext symbols. Decode ASCII escapes after the rotor transform.

Raw mode starts from the key's initial positions and advances once for every escaped symbol. State persists across all stdin chunks and pauses. Raw mode has no frame checksums, session markers, or recovery mechanism. A lost/inserted ciphertext symbol can desynchronize the remainder, and many valid-but-wrong symbols cannot be detected.

## Checked framing

Checked mode buffers 128 plaintext bytes by default. A full block is emitted immediately; the CLI also flushes a partial block after five seconds without input. Block size is configurable from 1 through 256 bytes. EOF flushes any remaining data and emits an explicit empty end frame. An empty input therefore still produces one end frame.

Every frame is:

```text
VVV(UNPADDED-UPPERCASE-BASE32)
```

The Base32 body uses `A–Z` and `2–7` without `=` padding. Parentheses delimit a frame; `VVV` provides Morse receiver acquisition training. There are no separators or newlines between emitted frames. The receiver can resynchronize at `(` even when training characters were lost.

Base32 encodes the following binary packet. Multi-byte integers use network byte order (big-endian). The fixed header is 32 bytes, equivalent to Python's `struct` format `!2sBB8sIHH8sI`.

| Byte offset | Size | Field |
| --- | --- | --- |
| 0 | 2 | Magic bytes `ER` (`45 52` in hexadecimal). |
| 2 | 1 | Protocol version, `1`. |
| 3 | 1 | Flag: `0` for data, `1` for end. Other values are invalid. |
| 4 | 8 | Session ID, generated from the operating system's random source for each encoder instance. |
| 12 | 4 | Unsigned sequence number, starting at zero. |
| 16 | 2 | Original plaintext byte length. |
| 18 | 2 | Ciphertext symbol/byte length, `L`. |
| 20 | 8 | Public machine fingerprint. |
| 28 | 4 | CRC32 of original plaintext bytes. |
| 32 | `L` | ASCII ciphertext symbols. |
| `32 + L` | 4 | CRC32 of the header and ciphertext, excluding this final CRC field. |

CRC32 is the standard CRC-32/ISO-HDLC calculation exposed by `zlib.crc32`, serialized as an unsigned 32-bit integer. It provides accidental-error detection only.

Data frames require a plaintext length of 1–256 and a ciphertext length between that length and three times that length. End frames require both lengths and the plaintext CRC to be zero. An end frame consumes its own sequence number. The encoder reserves sequence `0xFFFFFFFF` for an end frame: the largest permitted data sequence is `0xFFFFFFFE`. It raises an error rather than wrapping.

The maximum ciphertext length is 768 bytes; the maximum binary packet is 804 bytes; the maximum unpadded Base32 body is 1,287 characters. Including `VVV(` and `)`, the maximum frame is 1,292 symbols.

### Public machine fingerprint

Normalize a validated machine using its documented version-1 fields. Serialize it with recursively sorted object keys, no insignificant whitespace, ASCII JSON escaping, and unchanged array/string order. This is equivalent to:

```python
json.dumps(machine.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
```

Hash the resulting ASCII bytes using SHA-256 and retain the first eight digest bytes. The fingerprint contains no key settings. Changes to any public rotor, including an unused rotor, change the fingerprint.

### Independent block positions

For every data or end frame, compute:

```text
digest = SHA256(
    ASCII("EncryptedRadio/checked-v1/start") || 0x00 ||
    session_id[8 bytes] || sequence[4 bytes, big-endian]
)
```

Interpret the digest as a big-endian nonnegative integer. Repeatedly divide by 49, taking each remainder as an offset. Assign the first (least significant) base-49 digit to the leftmost selected rotor, then proceed rightward. Add each offset to that rotor's configured initial position, modulo 49. Reset the rotor stack to these derived positions for each frame, retaining its configured rings, rotor order, and plugboard.

This allows intact blocks to be decoded after a missing block. The offsets are public derivations; they are not a key derivation function or a modern security enhancement.

## Receive behavior and replacement transports

A checked decoder releases plaintext only after a closing delimiter and successful verification of canonical Base32, packet bounds, version/flags, public machine fingerprint, envelope CRC, rotor decoding, ASCII escapes, plaintext length, and plaintext CRC.

- An opening parenthesis abandons any partial frame and starts a new one. Invalid symbols, including the reception-error marker `?`, invalidate the current body. Oversized bodies are rejected with bounded buffering.
- Silence preserves partial frames and rotor state. Arbitrary input chunk boundaries have no protocol meaning.
- Verified sequence gaps produce diagnostics while allowing later valid plaintext through. Repeated or older frames are suppressed and reported. Skipped data is never fabricated.
- An unexpected new session reports a missing end marker for the previous unfinished session. The receiver remembers the most recent 64 superseded session IDs to suppress their delayed frames. This is bounded stream bookkeeping, not durable replay protection.
- Unexpected symbols outside frames are reported. A dangling preamble or partial frame at finite EOF is reported as truncation. A valid end marker is required to finish a checked session.
- The decoder retains its first 128 errors plus a diagnostic indicating further omissions; a separate counter records the total. Library `complete` means a valid terminal frame was received without trailing truncation. Consumers must also inspect `errors`: a completed session may contain earlier loss or corruption.

`rotorcrypt` writes payload only to stdout and diagnostics to stderr. Exit status is `0` on success, `1` for checked reception damage/loss, `2` for configuration/input failures, `130` on interruption, and `141` on a broken output pipe. Previously verified plaintext may already have been emitted before a later error. Use shell `set -o pipefail` to preserve pipeline failures.

A replacement transport accepts and emits the same ASCII symbols without knowing any rotor settings. It must preserve ordering and symbols, flush decoded output, and communicate detected uncertainty rather than silently dropping data. The Morse adapter's checked profile emits `?` on a decoding discontinuity; its raw profile stops because alignment cannot safely recover. Character/word timing is a transport concern: raw and checked modes do not turn long audio gaps into plaintext whitespace. Ordinary text-mode Morse is a separate unencrypted profile.

The [usage guide](USAGE.md) describes commands; the [architecture](ARCHITECTURE.md) describes component boundaries; the [validation record](VALIDATION.md) distinguishes automated tests from physical audio evidence.
