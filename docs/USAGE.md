# Installation and operation

## Environment

Install Python 3.12+, Make and [uv](https://docs.astral.sh/uv/getting-started/installation/).
`make sync` installs the locked `audio` and `demo` extras. `uv sync --locked`
installs both cipher CLIs and their base `cryptography` dependency without audio
or browser dependencies. The rotor implementation itself uses the standard library.
`uv sync --locked --extra demo` supports browser/WAV operation without PortAudio.
Linux live hardware needs the distribution's PortAudio runtime (Debian/Ubuntu:
`sudo apt-get install libportaudio2`) and the `audio` extra.

Full `make check` also uses Node.js 18+ to execute lightweight browser lifecycle
tests. Node is not required to run the applications or browser demo; there is no
frontend build step.

Activate with `. .venv/bin/activate`, or prefix commands with
`uv run --locked --extra audio --extra demo`. For uv at a nonstandard path, use
`make UV=/absolute/path/to/uv demo`. All tools support `--help`.

## Cipher streams

`rotorcrypt` provides the historical-style cipher shown below. For authenticated
encryption, use `sealcrypt` with the same input/output options and a freshly
generated shared key. Its [usage, key generation and protocol guide](SEALCRYPT.md)
explains the compatible pipelines, distinct key format and security boundaries.
Both endpoints must use `sealcrypt`; existing rotor keys and ciphertext cannot be
converted by changing the executable name alone.

```sh
mkdir -p secrets tmp
cp examples/example-key.json secrets/key.json
chmod 600 secrets/key.json
# Edit the local key; copying the public example alone does not make it secret.
rotorcrypt encrypt --machine examples/machine.json --key secrets/key.json \
  --input message.txt > tmp/ciphertext.txt
rotorcrypt decrypt --machine examples/machine.json --key secrets/key.json \
  --input tmp/ciphertext.txt > tmp/recovered.txt
```

`--text` accepts a complete argument; `--input` reads a file; otherwise stdin stays
open for streaming. Files/pipes preserve NUL and control bytes. Shell arguments
cannot carry NUL. Non-ASCII input is rejected. Diagnostics use stderr.

Set `set -o pipefail` in Bash so an upstream failure fails the entire pipeline.
Encryption at EOF writes the checked end frame and, for `sealcrypt`, an end record in raw mode
too. Ctrl-C is an interruption, not a successful finite transfer. Keep stderr
separate from payload. Terminals usually buffer until
Enter; use a producer writing a pipe for character-at-a-time input. Avoid `echo`
when an extra newline is unwanted.

## Raw and checked modes

Raw and checked describe streaming and recovery behavior; the selected cipher
determines the security properties. **`sealcrypt` authenticates records in both
modes. `rotorcrypt` provides no authentication in either mode.**

| Cipher and mode | Streaming behavior | Validation and recovery |
| --- | --- | --- |
| `rotorcrypt --mode raw` | Emits encoded cipher symbols immediately and keeps uninterrupted rotor state across chunks. | No integrity checks or end frame. Missing symbols can desynchronize the remaining stream without reliable detection. |
| `rotorcrypt --mode checked` | Buffers plaintext into independently encrypted blocks. | Checks lengths, configuration, CRCs and sequence before releasing each block. Requires an end frame for successful completion. Reports damaged/missing blocks and resumes on later intact blocks; CRCs do not prevent forgery. |
| `sealcrypt --mode raw` | Emits each available input chunk as one or more authenticated records. Decryption waits for a complete verified record. | Stops on detected integrity or ordering errors. Requires an authenticated end record. |
| `sealcrypt --mode checked` | Buffers plaintext into independently authenticated records. | Releases only verified records, reports loss or damage, and resumes on later intact records. Requires an authenticated end record. |

Checked mode is the default. Both ciphers flush checked encryption at
`--block-size` plaintext bytes (default 128, allowed 1–256), after
`--idle-seconds` without new input (default 5), or at EOF. In sealcrypt raw mode,
`--block-size` caps record size without waiting for a full block. Pauses never
reset either cipher's state; a partial rotor raw escape waits for more symbols.

Both endpoints need matching cipher, mode, public machine configuration and the
appropriate shared key. The same public machine JSON schema works with either
cipher, but rotor and seal keys and wire formats are distinct. See the
[rotor protocol](PROTOCOL.md) and [sealcrypt protocol](SEALCRYPT.md).

For Morse pipelines, pair `--mode checked` with `morselink --profile checked`
(both defaults), or pair `--mode raw` with `--profile raw` for both transmission
and reception. `--profile text` is ordinary unencrypted Morse and normalizes case
and whitespace; it is not an exact cipher transport.

Checked recovery does not reconstruct missing content. A finite decrypt command
returns nonzero after corruption, loss, truncation or a missing end record, even
if later valid blocks produced plaintext. Cipher exit statuses are 0 for success,
1 for stream integrity errors, 2 for configuration/input errors, 130 for an
interrupt and 141 for a broken pipe. Keep diagnostics on stderr so recovery
messages cannot enter a downstream payload stream.

## WAV, speaker and microphone

```sh
mkdir -p tmp
morselink devices
morselink tx --profile text --text 'HELLO WORLD' --output-wav tmp/hello.wav
morselink rx --profile text --input-wav tmp/hello.wav
morselink tx --profile text --frequency 700 --wpm 20 --text 'HELLO WORLD'
morselink rx --profile text --frequency 700 --wpm 20
```

Use `--device` with a device index or name for live operation. TX/RX are exclusive.
TX consumes streaming stdin until EOF and drains queued audio. Microphone RX does
not consume text stdin and runs until interrupted. Callback overflow/underflow
is an explicit error; capture queues hold at most two seconds. A stalled downstream
process can cause an unrecoverable capture discontinuity.

Automatic reception searches 400–1200 Hz and 8–30 WPM and locks one foreground
signal. Short/all-dot messages may remain ambiguous; specify `--wpm` rather than
expecting language correction. `--frequency` selects a known tone;
`--sample-rate` selects the live device rate. WAV reception uses the actual file
rate and accepts mono uncompressed integer PCM.

## Demonstrations

`er-demo` and its browser rotor controls demonstrate `rotorcrypt`. Use the offline
WAV pipeline in the [sealcrypt guide](SEALCRYPT.md) to exercise authenticated
encryption through the same Morse encoder and audio decoder.

```sh
make demo
er-demo roundtrip --scenario noisy --output-dir tmp/demo-noisy
er-demo roundtrip --scenario lost-block --output-dir tmp/demo-loss
er-demo roundtrip --mode raw --text 'Mixed Case!' --output-dir tmp/demo-raw
make demo-web
```

Clean/noisy cases exit zero only when recovered output matches expected bytes
without errors. The lost-block case uses 16-byte blocks, removes the second data
frame's physical samples, and requires a reported gap plus exact recovery of all
remaining blocks. It needs checked mode and at least 33 input bytes. Reports show
removed sample spans and actual decoder output. Failure returns nonzero.

The browser at <http://127.0.0.1:8765> offers configuration, offline jobs, WAV
upload/download/playback and live WebSocket transmission/reception. Microphone
permission follows an explicit Receive action; capture uses the actual AudioContext
sample rate. Stop closes the active operation. Configuration stays in memory;
JSON imports contain data, not filesystem paths.

Browser limits: 512 ASCII input bytes, 64 MiB WAV uploads, ten minutes per audio
operation and two seconds of queued PCM. Duration is shown before playback.
Large checked messages can exceed ten minutes because Morse framing is verbose;
shorten the message, raise speed, use raw/text as appropriate, or use the CLI.
Live and offline results are labeled separately. Non-loopback binding is rejected.
