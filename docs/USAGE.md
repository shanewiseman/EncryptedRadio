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

## Text encoding

Both cipher commands now use **lowercase-first by default** for encryption and
decryption. Add **`--uppercase-first`** to select the previous behavior. The longer
`--text-encoding uppercase-first` is equivalent; `--text-encoding ascii` remains
a legacy alias. The shorthand and `--text-encoding` are mutually exclusive.

Lowercase-first reversibly swaps ASCII letter case at the cipher boundary, so
the recovered message retains its exact original capitalization, spaces and
control bytes. This is different from converting the message to uppercase.

For rotorcrypt, original lowercase letters then cost one symbol each and original
uppercase letters cost three. The example `This message is encrypted using wwii technology`
shrinks from 139 to 61 raw ciphertext symbols; spaces still cost three each.
Uppercase-heavy text may grow. Sealcrypt also accepts the option and preserves
case, but gains no size reduction because it encrypts bytes without escaping.

Select the same encoding when encrypting and decrypting, including uploaded WAVs
and live reception. Checked rotor frames and both seal modes carry an encoding
flag and reject a mismatched selection. Older receivers reject lowercase-first
frames. **Raw rotor streams have no encoding marker and cannot detect a mismatch**;
use `--uppercase-first` for recordings made with the previous default, including
existing raw ciphertext. An explicit `--text-encoding lowercase-first` still works
for recordings made with that option. The setting does not change either audio
transport or add encryption to plain text mode.

For example, using the public demonstration rotor key:

```sh
set -o pipefail
mkdir -p tmp
rotorcrypt encrypt --mode raw \
  --machine examples/machine.json --key examples/example-key.json \
  --text 'This message is encrypted using wwii technology' \
  | morselink tx --profile raw --output-wav tmp/lowercase.wav
morselink rx --profile raw --input-wav tmp/lowercase.wav \
  | rotorcrypt decrypt --mode raw \
      --machine examples/machine.json --key examples/example-key.json
```

This example needs no encoding flag and uses 61 raw ciphertext symbols. To use
the original uppercase-first encoding, add `--uppercase-first` to **both** cipher
commands; the same example then uses 139 raw symbols. The receiver never infers
the selected encoding from the message's apparent capitalization.

Use the same override with `sealcrypt` and its separate key. Either pipeline can
use `audiolink` at both ends instead of `morselink`. Neither transport needs a
text-encoding option. The browser's **Text encoding** selector starts at
**Lowercase-first (default)**; choose **Uppercase-first (legacy)** for older default
recordings. `er-demo roundtrip` also defaults to lowercase-first and accepts
`--uppercase-first`. The shared Python code handles encryption and decryption.
Plain text mode keeps its existing transport normalization and does not accept an
explicit lowercase-first selection.

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

Both endpoints need matching cipher, mode, text encoding, public machine
configuration and the appropriate shared key. The same public machine JSON schema works with either
cipher, but rotor and seal keys and wire formats are distinct. See the
[rotor protocol](PROTOCOL.md) and [sealcrypt protocol](SEALCRYPT.md).

For either audio transport, pair cipher `--mode checked` with transport
`--profile checked` (both defaults), or pair `--mode raw` with `--profile raw` for
transmission and reception. `--profile text` bypasses encryption and normalizes
case and whitespace; it is not an exact cipher transport. Both endpoints must use
the same transport: Morse and packet AFSK waveforms are not interchangeable.

The transport has its own buffering and framing. `audiolink` adds packets and
error checks even in its raw profile; raw means stop on detected errors, not
unframed PCM or removal of cipher authentication. Its error correction can repair
bounded bit damage but does not reconstruct missing cipher records.

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

## Packet audio

`audiolink` preserves the same `tx`, `rx`, `devices`, text/file/stdin, WAV, live
sound device and profile interfaces. It uses fixed 1,200/2,200 Hz AFSK tones at
1,200 bits/s; Morse `--frequency` and `--wpm` settings do not apply. The actual
payload rate includes packet, coding and acquisition overhead. Default data
packets hold up to 128 ASCII bytes and flush after 0.25 idle seconds or at EOF.
Use `--packet-size` and `--idle-seconds` to change that buffering; it is separate
from the cipher's own block size and idle timer. Packetized reception releases
verified packets rather than one decoded character at a time.

```sh
audiolink devices
audiolink tx --profile text --text 'HELLO WORLD' --output-wav tmp/hello-afsk.wav
audiolink rx --profile text --input-wav tmp/hello-afsk.wav
sealcrypt encrypt --machine examples/machine.json --key secrets/seal-key.json \
  --input message.txt | audiolink tx --output-wav tmp/sealed-afsk.wav
audiolink rx --input-wav tmp/sealed-afsk.wav \
  | sealcrypt decrypt --machine examples/machine.json --key secrets/seal-key.json
```

WAV and microphone reception use the same Python decoder. Queue bounds, stderr
separation, EOF draining and device errors follow the live-audio behavior above.
The modem targets a conventional analog voice-audio path under declared synthetic
channel assumptions; no handheld-radio interoperability has been established.
See [AUDIOLINK.md](AUDIOLINK.md) for framing, controls and validation boundaries.

## Demonstrations

`er-demo` and the browser select the cipher and transport independently. All four
combinations use the actual Python cipher, audio encoder, audio decoder and
plaintext verification. Omitting selections preserves the rotor/Morse default.

```sh
make demo
er-demo roundtrip --scenario noisy --output-dir tmp/demo-noisy
er-demo roundtrip --scenario lost-block --output-dir tmp/demo-loss
er-demo roundtrip --mode raw --text 'Mixed Case!' --output-dir tmp/demo-raw
er-demo roundtrip --cipher sealcrypt --transport audiolink --output-dir tmp/demo-sealed-afsk
er-demo roundtrip --cipher rotorcrypt --transport audiolink --scenario noisy --output-dir tmp/demo-rotor-afsk
er-demo roundtrip --cipher sealcrypt --transport morselink --key secrets/seal-key.json
make demo-web
```

Clean/noisy cases exit zero only when recovered output matches expected bytes
without errors. The lost-block case uses 16-byte blocks, removes the second data
frame's physical samples, and requires a reported gap plus exact recovery of all
remaining blocks. It needs checked mode and at least 33 input bytes. Reports show
removed sample spans and actual decoder output. Failure returns nonzero.

The browser at <http://127.0.0.1:8765> offers configuration, offline jobs, WAV
upload/download/playback and live WebSocket transmission/reception. Microphone
permission follows an explicit **Receive microphone** or **Acoustic round trip**
action; capture uses the actual AudioContext
sample rate. Stop closes the active operation. Select the cipher and transport
before preparing playback or starting reception; controls for the other method
are not used. Rotor controls edit ordered rotors, positions, rings and plugboard;
seal controls generate/import a separate shared key. Configuration stays in
memory; JSON imports contain data, not filesystem paths.

A seal demo without an explicit key uses a newly generated in-memory key. Generated
keys are omitted from reports and artifacts; retain/import your own key when
receiving another process's transmission or decoding an older WAV. Reloading the
browser can replace its generated key. Text mode has no encryption or key use.

Browser limits: 512 ASCII input bytes, 64 MiB WAV uploads, ten minutes per audio
operation and two seconds of queued PCM. Duration is shown before playback.
Large checked messages can exceed ten minutes because Morse framing is verbose;
shorten the message, raise Morse speed, choose `audiolink`, or use the CLI. Choose
raw/text only when their different validation or plaintext behavior is intended.
Live and offline results are labeled separately. Non-loopback binding is rejected.

### Single-tab acoustic round trip

Use **Acoustic round trip** to send a finite message through your speakers while
the same tab listens through your microphone:

1. Choose the cipher, transport, mode and text encoding, and enter a short,
   nonempty message. Both directions share these settings and the same key.
   Plain text must contain more than whitespace.
2. Click **Acoustic round trip** and allow microphone access. Capture is armed
   before playback; the prepared transmission shows its actual duration.
3. Use speakers so the microphone can hear the sound, then click **Play**.
   Begin at a comfortable volume and keep the microphone away from the speaker
   if reception clips or distorts.
4. Let playback finish. The microphone keeps listening for one second after all
   queued sound has played, then the remaining captured audio is decoded and
   reception finishes automatically. Inspect recovered text, the match result and
   decoder diagnostics in the microphone result area.

The result comes from microphone PCM processed by the real Python decoder.
Speaker volume, microphone placement, room reflections and browser/device audio
processing can affect recovery. This operation does not feed microphone audio
back to the speakers. **Stop** cancels both directions and releases the microphone
and audio context; it is not a successful completed transfer.

Checked and raw modes compare recovered plaintext byte-for-byte with your input.
Plain text mode bypasses encryption and reports a match after the selected
transport's case/whitespace normalization. Offline results remain separate. The
**Keep separate transmission open for more text** option applies to standalone
transmission; acoustic round trip always sends the complete message present when
it starts.
