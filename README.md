# EncryptedRadio

Composable Linux-first Python applications: **rotorcrypt** preserves every ASCII
byte through a configurable Enigma-style cipher; **sealcrypt** offers authenticated
ChaCha20-Poly1305 encryption with the same CLI and streaming options; **morselink**
transmits and receives their text through Morse audio. **er-demo** demonstrates the
rotor pipeline in the terminal and a local browser. A different transport can
replace morselink by preserving the ASCII character stream.

The rotor cipher is experimental historical-style encryption, **not modern
cryptographic security**. Its CRCs detect accidental corruption, not forgery.
`sealcrypt` verifies authentication tags before releasing plaintext, using a separate
256-bit key. Neither application protocol has been independently audited. Public
demonstration keys provide no secrecy. See [security limitations](SECURITY.md).

## Install and run

Use Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and Make.
Install Node.js 18+ to run the complete browser lifecycle test coverage in `make check`;
the applications and browser demo do not require Node or a frontend build step.

```sh
make sync
make check
make demo
make demo-web
```

`make demo` runs plaintext → rotor encryption → WAV synthesis → actual PCM decoding
→ decryption and compares the recovered bytes. Artifacts are saved in ignored
`tmp/demo/`. It runs faster than real time and needs no audio device or PortAudio.
`make demo-web` serves the browser interface at <http://127.0.0.1:8765>.
The browser uses the same Python implementation, with local WAV playback and
optional microphone capture after an explicit action. Its cipher controls support
`rotorcrypt`; use the [sealcrypt WAV pipeline](docs/SEALCRYPT.md) for an authenticated
round trip. Native Linux speaker and microphone access through `morselink` also
needs PortAudio (`sudo apt-get install libportaudio2` on Debian/Ubuntu).

Activate the environment for the remaining commands:

```sh
. .venv/bin/activate
er-demo roundtrip --scenario noisy --output-dir tmp/demo-noisy
er-demo roundtrip --scenario lost-block --output-dir tmp/demo-loss
morselink devices
```

The loss demo removes the actual audio for one 16-byte plaintext block. It succeeds
when the receiver reports the missing block and recovers later blocks. Its report
explicitly says that the original message did not match in full.

## Authenticated encryption with sealcrypt

Generate a new key, then substitute `sealcrypt` for `rotorcrypt` at both ends:

```sh
sealcrypt keygen --key secrets/seal-key.json
set -o pipefail
sealcrypt encrypt --machine examples/machine.json --key secrets/seal-key.json \
  | morselink tx
morselink rx \
  | sealcrypt decrypt --machine examples/machine.json --key secrets/seal-key.json
```

It accepts the same `--text`, `--input`, stdin, mode, block-size and idle options.
The public machine file is authenticated context; its rotors are not used for
encryption. Rotor key files/ciphertext cannot be reused. Raw mode flushes immediately
but still authenticates complete records before decryption releases their contents.
See [sealcrypt usage and protocol](docs/SEALCRYPT.md) for key handling and boundaries.

## Compose the rotor applications

The example key is public and intended only for demonstrations. Create a local key
under ignored `secrets/` using the [configuration format](docs/PROTOCOL.md).
The CLI requires explicit machine and key paths.

```sh
set -o pipefail

# Transmit through the Linux default speaker. EOF drains queued audio.
rotorcrypt encrypt --machine examples/machine.json --key examples/example-key.json \
  | morselink tx

# Receive from the microphone until Ctrl-C.
morselink rx \
  | rotorcrypt decrypt --machine examples/machine.json --key examples/example-key.json

# Write and decode a WAV without opening a device.
mkdir -p tmp
rotorcrypt encrypt --machine examples/machine.json --key examples/example-key.json \
  --text 'Meet at 09:30!' \
  | morselink tx --output-wav tmp/message.wav
morselink rx --input-wav tmp/message.wav \
  | rotorcrypt decrypt --machine examples/machine.json --key examples/example-key.json

# Ordinary Morse: uppercase text with normalized word spaces.
morselink tx --profile text --text 'HELLO WORLD'
morselink rx --profile text
```

The cipher and transport commands flush available output. Stdout contains payload;
diagnostics go to stderr. Interactive terminals normally deliver a line after Enter;
the programs do not disable terminal line buffering. A checked block flushes at
128 bytes, after five idle seconds, or at EOF. Morse is slow: the browser shows the
actual transmission duration before playback.

Checked mode is the default for both ciphers: it buffers independent blocks,
reports damaged or missing content, and can recover subsequent intact blocks.
Raw mode reduces buffering: `rotorcrypt` keeps a continuous rotor state without
integrity checks, while `sealcrypt` still authenticates every record and stops on
detected stream errors. Match the cipher's `--mode` to morselink's `--profile` at
both ends. See the [raw/checked comparison](docs/USAGE.md#raw-and-checked-modes)
and [operation and installation guide](docs/USAGE.md).

## Project records

- [Project scope and acceptance status](docs/PROJECT.md)
- [Architecture](docs/ARCHITECTURE.md) and [protocol/configuration](docs/PROTOCOL.md)
- [Authenticated encryption with sealcrypt](docs/SEALCRYPT.md)
- [Reproducible validation and hardware checklist](docs/VALIDATION.md)
- [AI contributor guidance](AGENTS.md) and [contributing](CONTRIBUTING.md)
- [Architecture decisions](docs/decisions/README.md)
- [GitHub configuration and protected master](docs/GITHUB.md)
- [Change history](CHANGELOG.md), [support](SUPPORT.md), and [code of conduct](CODE_OF_CONDUCT.md)

## License

No license has been selected. This repository does not grant a license to use,
modify, or distribute its contents. A maintainer must decide licensing before a
licensed release.
