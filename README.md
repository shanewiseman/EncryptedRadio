# EncryptedRadio

Two composable Linux-first Python applications: **rotorcrypt** preserves every ASCII
byte through a configurable Enigma-style cipher; **morselink** transmits and receives
their text through Morse audio. **er-demo** demonstrates the complete pipeline in
the terminal and a local browser. A different transport can replace morselink by
preserving the ASCII character stream.

This is experimental historical-style encryption, **not modern cryptographic
security**. CRCs detect accidental corruption; they do not authenticate a sender.
Public demonstration keys provide no secrecy. See [security limitations](SECURITY.md).

## Install and run

Use Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and Make.
On Debian/Ubuntu, live speaker and microphone access needs PortAudio:

```sh
sudo apt-get install libportaudio2
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
optional microphone capture after an explicit action.

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

## Compose the applications

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

Both text-producing applications flush available output. Stdout contains payload;
diagnostics go to stderr. Interactive terminals normally deliver a line after Enter;
the programs do not disable terminal line buffering. A checked block flushes at
128 bytes, after five idle seconds, or at EOF. Morse is slow: the browser shows the
actual transmission duration before playback.

Use `--mode raw` on rotorcrypt and `--profile raw` on morselink for an uninterrupted
rotor stream. Both ends must start with the same settings. Raw mode has no loss
recovery. Checked mode, the default, frames independently encrypted blocks and
recovers after a missing or damaged block. It reports missing content without
reconstructing it. See [operation and installation](docs/USAGE.md).

## Project records

- [Project scope and acceptance status](docs/PROJECT.md)
- [Architecture](docs/ARCHITECTURE.md) and [protocol/configuration](docs/PROTOCOL.md)
- [Reproducible validation and hardware checklist](docs/VALIDATION.md)
- [AI contributor guidance](AGENTS.md) and [contributing](CONTRIBUTING.md)
- [Architecture decisions](docs/decisions/README.md)
- [GitHub configuration and protected master](docs/GITHUB.md)
- [Change history](CHANGELOG.md), [support](SUPPORT.md), and [code of conduct](CODE_OF_CONDUCT.md)

## License

No license has been selected. This repository does not grant a license to use,
modify, or distribute its contents. A maintainer must decide licensing before a
licensed release.
