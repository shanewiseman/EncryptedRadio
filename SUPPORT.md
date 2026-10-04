# Support

EncryptedRadio provides the `rotorcrypt` and `sealcrypt` cipher commands, the
`morselink` Morse transport, and terminal/browser rotor demonstrations through
`er-demo`. Installation and command examples are in [README.md](README.md) and
[the usage guide](docs/USAGE.md). The project has no service commitments, and
licensing remains undecided.

For project questions, defects, or proposals, search existing GitHub issues first
and then open an issue if needed. A useful reproduction includes:

- The affected command or browser operation, repository revision, and exact command
  line with private paths and values removed.
- Cipher mode (`checked` or `raw`), Morse profile (`checked`, `raw`, or `text`), and
  input source: `--text`, file, stdin, WAV, microphone, or browser streaming.
- Expected and actual output, exit status, and sanitized stderr. Use synthetic
  plaintext and public demonstration settings; never attach a private key file.
- OS and Python version; browser/Node.js versions for browser failures; audio
  device, sample rate, frequency and speed for audio failures. State whether the
  failure occurs offline with a WAV or only through physical devices.

Use [sealcrypt documentation](docs/SEALCRYPT.md) for authenticated encryption and
key handling. Raw/checked behavior differs between the two ciphers; identify which
one is involved. `er-demo` and the browser currently demonstrate the rotor cipher,
not sealcrypt. Check [validation evidence and remaining hardware acceptance](docs/VALIDATION.md)
before treating a synthetic test result as a hardware guarantee.

Use the [task template](docs/TASK_TEMPLATE.md) for implementation requests. Remove
keys, credentials, private traffic, personal information and private prompts from
all reports, logs and examples.

Report vulnerabilities through the private process in [SECURITY.md](SECURITY.md). Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) in all project interactions.

Development starts with [README.md](README.md), [AGENTS.md](AGENTS.md), and [CONTRIBUTING.md](CONTRIBUTING.md). Product requirements and unresolved decisions are tracked in [docs/PROJECT.md](docs/PROJECT.md).
