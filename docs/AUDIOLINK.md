# audiolink: packet audio transport

`audiolink` is a separate packet audio transport with the same text-pipe, WAV and
live-audio interfaces as `morselink`. It uses continuous-phase AFSK at 1,200 bits/s,
with 1,200 Hz and 2,200 Hz tones, packet checks and forward error correction.
It carries the existing cipher symbols unchanged and never receives cipher keys.

The target is a conventional handheld analog voice-radio audio path. The Midland
GXT3000 is a capability reference, not equipment selected for deployment. This document
defines engineering constraints; it does not choose a radio service or deployment.

## Reference capabilities and assumptions

The [GXT3000 manual](https://cdn.shopify.com/s/files/1/0531/2856/0817/files/GXT3000_Owner_s_Manual_Rev_A2__Final-compressed.pdf?v=1734379224)
documents external speaker/microphone connections, half-duplex operation and
Wide/Narrow settings. USB-C is documented for charging. It does not specify a
numeric end-to-end audio passband, electrical accessory pinout, or general-purpose
data interface. No exact GXT3000 response or modem compatibility is assumed.

| Property | Engineering target |
| --- | --- |
| Channel | One foreground mono signal through a half-duplex analog voice-audio path. |
| Audio bandwidth | Start with a nominal 300–3,000 Hz channel model with realistic attenuation and roll-off. This is a provisional design assumption, not a measured GXT3000 specification. |
| Interfaces | Ordinary audio input/output. Do not depend on USB audio, a radio data port, direct RF/IQ access, or radio firmware changes. |
| Host PCM | Support 44.1 and 48 kHz audio, using the actual input rate and preserving state across arbitrary chunk boundaries. Host sample rate does not imply radio audio bandwidth. |
| Level and response | Account for frequency-dependent gain, pre/de-emphasis, tone imbalance, noise and clipping/limiting. Do not assume a flat, linear, full-range soundcard connection. |
| Burst timing | Use a fixed acquisition preamble and configurable key-up lead-in and tail guards. Model transmitter startup and receiver squelch clipping the beginning or end of a burst. |
| Silence | Input pauses are normal. Silence alone must not create an error, expire a partial valid transfer or reset the cipher. |
| Delivery | Preserve ordered payload, expose unrecoverable loss, and bound memory and queues. Acknowledgements and retransmission are not assumed. |

The GXT3000's Wide/Narrow setting concerns radio operation; it is not evidence
that the audio path passes the previously tested ggwave signal's upper tones.

## Modem selection

The selected modulation is **1,200-bit/s AFSK with 1,200/2,200 Hz tones**, an
established analog-FM packet-radio approach documented by
[Dire Wolf](https://raw.githubusercontent.com/wb2osz/direwolf/dev/doc/User-Guide.pdf).
This implementation uses its own packet protocol; it does not claim AX.25 or
Dire Wolf interoperability. The gross bit rate is not the useful payload rate:
packet headers, error correction, acquisition and guards consume airtime.
Tone frequencies alone do not describe modulation sidebands or occupied bandwidth;
validation must send the complete waveform through the declared channel model.

The existing [ggwave audible profile](https://github.com/ggerganov/ggwave#technical-details)
uses tones from approximately 1.875 to 6.33 kHz. Its earlier clean-loopback results
demonstrate a faster full-band audio transport, but do not establish compatibility
with this narrower target. Do not use that profile's speedup as an audiolink
acceptance result. A different or reconfigured backend must be benchmarked anew.

Packet framing protects payload length and sequence metadata along with the
payload, with CRC32, forward error correction and an explicit end packet. Transport
checks and error correction do not replace cipher authentication. Select the same
transport and profile at both ends; Morse and packet AFSK waveforms differ.

## Application interface

- `tx`, `rx`, device selection/enumeration, `--text`, `--input`, streaming
  stdin/stdout, WAV input/output and half-duplex live operation follow the
  corresponding `morselink` interfaces.
- Checked/raw profiles preserve ASCII bytes without interpreting cipher keys,
  decrypting records or removing cipher framing. The ordinary text profile
  applies its documented normalization separately.
- Stdout carries payload only; stderr carries diagnostics. Output is incremental,
  PCM queues are bounded, discontinuities are explicit, EOF drains transmission,
  and live operations can be cancelled.
- Checked mode reports detected loss and allows later intact cipher records to
  recover; raw mode fails on detected corruption or loss. Never silently join
  data across a missing transport packet. Keep payload buffering and idle-flush
  policy distinct from PCM queue limits.
- Morse-specific `--wpm` and single-tone `--frequency` arguments are not accepted
  as packet modem settings.
- WAV and live adapters use the same Python modem/DSP implementation.
  Vendor-specific PTT control is not implemented.

## Commands and demonstration

```sh
# Exact checked cipher transport; substitute rotorcrypt if desired.
set -o pipefail
sealcrypt encrypt --machine examples/machine.json --key secrets/seal-key.json \
  | audiolink tx
audiolink rx \
  | sealcrypt decrypt --machine examples/machine.json --key secrets/seal-key.json

# Device-free packet audio.
audiolink tx --profile text --text 'HELLO WORLD' --output-wav tmp/hello-afsk.wav
audiolink rx --profile text --input-wav tmp/hello-afsk.wav

# Real cipher/audio/decoder round trip, with an ephemeral seal demo key.
er-demo roundtrip --cipher sealcrypt --transport audiolink --output-dir tmp/demo-sealed-afsk
make demo-web
```

`--text` and `--input` are mutually exclusive; otherwise TX reads open stdin.
RX uses `--input-wav` or the microphone, never text stdin. `--sample-rate` selects
the live rate; WAV reception uses the file rate. `--device` selects a live device,
and `audiolink devices` enumerates devices. Payload goes to stdout; diagnostics go
to stderr. TX drains at EOF, while microphone RX continues until interrupted.
Partial packets flush after `--idle-seconds` (default 0.25 seconds) without new
input, at the packet-size limit or at EOF. This transport buffering is separate
from the cipher's checked block/idle settings. Smaller packets reduce fill delay
but increase airtime overhead. A receiver releases each packet only after its
checks pass; the downstream cipher may still need a complete record.

For exact cipher transport, match `--mode checked` with `--profile checked`, or
`--mode raw` with `--profile raw`. The text profile uppercases and normalizes
ordinary text and therefore must not be used for ciphertext. Checked errors emit
`?` to invalidate the cipher's current frame and permit later recovery. Raw
reception stops on detected corruption or loss. Missing end signaling makes a
finite transfer incomplete. Error correction has bounded capability and cannot
reconstruct a wholly missing packet.

The browser offers independent cipher and transport choices for offline round
trips, WAV upload/download and live audio. It uses the same Python decoder; no
predetermined decoded text or JavaScript modem is involved. The browser shows
actual transmission duration and retains its existing input, queue, upload and
duration limits. See [USAGE.md](USAGE.md) for key handling and browser bounds.

## Packet protocol v1

Each encoder chooses a random eight-byte session identifier and starts its
sequence at zero. A packet consists of a mark-tone lead, 96 alternating training
bits, the 64-bit sync word `D391DA26C5A74E18` (most-significant bit first), the
coded header, the coded body, and a silent tail. A one bit selects 1,200 Hz; a
zero selects 2,200 Hz. Tone phase remains continuous across bit transitions;
short amplitude ramps apply at burst edges.

The uncoded header is network byte order, `struct.Struct("!2sBB8sIH")`, followed
by its CRC32:

| Offset | Bytes | Field |
| --- | --- | --- |
| 0 | 2 | Magic `AL` |
| 2 | 1 | Version 1 |
| 3 | 1 | Data flag 0 or end flag 1 |
| 4 | 8 | Random session identifier |
| 12 | 4 | Sequence number |
| 16 | 2 | Payload byte length |
| 18 | 4 | CRC32 of the preceding 18 header bytes |

Data packets carry 1–256 ASCII bytes. The empty end packet has length zero and
uses the next sequence number. Counters never wrap; sequence `0xFFFFFFFF` is
reserved for an end packet. The body consists of payload
bytes followed by CRC32 of the complete 22-byte header plus payload.

Header and body are encoded separately. Each byte is split high nibble first;
each nibble becomes an extended Hamming(8,4) codeword. Data occupies positions
3, 5, 6 and 7; even parity occupies 1, 2 and 4, with overall parity at position 8.
Within each coded region, transmit bit plane 1 of all codewords, then plane 2,
and so on. This interleaving spreads adjacent channel errors across codewords.
The code corrects one bit per codeword and detects two; CRC32 validates the
reconstructed header and body. Larger errors may exceed both checks' guarantees.
None of these fields provides cryptographic authentication.

The default packet payload limit is 128 bytes. `--packet-size` accepts 1–256;
`--lead-ms` defaults to 200 and `--tail-ms` to 50, each accepting 0–2,000 ms.
Both guards apply to every packet, including the end packet. These are soundcard
waveform settings, not vendor-specific PTT controls. The initial wire version
fixes bit rate and tone frequencies. `--wpm` and `--frequency` are not audiolink
controls. The browser uses the default packet settings.

The decoder band-passes PCM, correlates the two known tones, searches sync and
sampling phase, and tries bounded sample-clock adjustments. It validates header
lengths before buffering a body and releases only verified ASCII payloads. It
keeps packet acquisition independent of transmitter chunk boundaries. It reports
sequence gaps and suppresses repeated/old packets; silence does not expire state.
Its recent-session cache holds at most 64 entries and is not durable replay
protection.
Checked/text diagnostics emit `?`, while raw raises immediately. End-of-input
reports a partial acquired packet or an acquired transfer without an end packet;
ordinary silence with no acquired packet is not an error.

One data packet carrying *L* bytes has `576 + 16L` modulated bits, before guards.
At the default sample rate/settings its duration is `(576 + 16L) / 1200 + 0.25`
seconds. An end packet adds 0.73 seconds. Small partial packets therefore have
proportionally higher overhead. Finite WAV duration is measured from actual PCM
frame counts; streaming flushes and chunk sizes can change packet overhead.

## Comparison and acceptance evidence

Compare the packet modem with Morse using the same plaintext and identical checked
cipher output. Measure actual synthesized WAV frame counts, including all
packet/coding overhead, preambles, guards, pauses and end signaling. The
[validation record](VALIDATION.md#voice-band-transport-comparison) records a
20-word comparison through the same 300–3,000 Hz filter: 8.89 seconds for the
393-symbol checked sealcrypt stream versus 276.90 seconds for 20-WPM Morse in
that run. It separates measured synthetic evidence from remaining hardware
acceptance. Reproduce it with:

```sh
uv run --locked --extra demo python scripts/benchmark_transports.py --output-dir tmp/audiolink-comparison
```

Run a clean PCM baseline, followed by filtered-channel cases. Define and record
filter response, pre/de-emphasis and gain settings, clipping level, noise spectrum
and SNR measurement convention before presenting results. Include sample-clock
mismatch, arbitrary PCM chunk boundaries and burst-start/end truncation. Treat
speech processing or companding as separate exploratory cases unless validated.

Receivers must recover data from PCM alone, without the expected payload or
transmitter packet boundaries. Require exact received ciphertext and decrypted
plaintext plus successful stream completion and no diagnostics for a passing
case. Report failures, recovery, latency and useful throughput separately; an
undecodable short waveform is not a speedup.

Synthetic tests establish behavior under the declared model. They do not establish
GXT3000 compatibility, physical range, or an acoustic/radio performance guarantee.
Only impairment cases exercised by reproducible tests are evidence of supported
behavior; the initial channel model is not a measured device specification.
