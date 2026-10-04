# Installation and operation

## Environment

Install Python 3.12+, Make and [uv](https://docs.astral.sh/uv/getting-started/installation/).
`make sync` installs the locked `audio` and `demo` extras. The cipher uses the
standard library; `uv sync --locked` installs a cipher-only environment.
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

Checked encryption flushes at a block boundary, at EOF, or after an idle interval
(`--idle-seconds`, default 5). Checked reception releases plaintext only after
validation. Raw mode streams immediately and keeps rotor state across chunks.
An incomplete raw escape waits for subsequent symbols. Pauses never reset cipher state.

Set `set -o pipefail` in Bash so an upstream failure fails the entire pipeline.
EOF writes the checked end frame; Ctrl-C is an interruption, not a successful
finite transfer. Keep stderr separate from payload. Terminals usually buffer until
Enter; use a producer writing a pipe for character-at-a-time input. Avoid `echo`
when an extra newline is unwanted.

## WAV, speaker and microphone

```sh
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
