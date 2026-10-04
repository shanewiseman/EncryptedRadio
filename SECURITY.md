# Security policy

## Current status

EncryptedRadio offers two distinct cipher commands over the same ASCII transport. `rotorcrypt` implements experimental Enigma-style encryption and does **not** provide modern cryptographic security or authentication. `sealcrypt` uses the `cryptography` implementation of ChaCha20-Poly1305 authenticated encryption, with HKDF-SHA256 session keys. Its application protocol is new and unaudited; neither command is a supported production communications system. Passing tests establish specific functional behavior, not a security audit.

The custom rotor construction was explicitly selected for this educational/experimental application. CRC32 checks detect accidental transmission damage and many incorrect-key results. An attacker can recompute them. The SHA-256 block-offset derivation and public machine fingerprint do not authenticate messages or turn the rotor cipher into modern encryption.

`sealcrypt` protects record confidentiality and detects record forgery or modification by parties without the shared key. It authenticates the header and public machine context before releasing plaintext or changing session/sequence state. Fresh random session salts derive independent keys, and per-session sequence nonces never wrap. Both endpoints need `sealcrypt` and a new random 256-bit key; rotor keys and ciphertext are incompatible. See the [authenticated protocol and threat model](docs/SEALCRYPT.md).

## Threat model and boundaries

Both checked protocols report loss, corruption, duplication, and reordering, validate complete blocks before releasing plaintext, and can resume with subsequent valid blocks. `rotorcrypt` raw mode deliberately lacks these checks and can silently produce incorrect output after symbol damage. `sealcrypt` raw mode still authenticates complete records and an end marker; it terminates on the first detected integrity or ordering error. Its decryption therefore waits for a complete record. Previously emitted, verified plaintext cannot be retracted if a later record fails, so callers must check exit status.

The assets are plaintext, private rotor settings, shared encryption keys, and locally generated recordings. Their relevant boundaries are:

- **Local files and processes:** private configurations and plaintext are visible to the invoking account and processes able to access their files, memory, terminal, or command-line arguments. The application does not defend against a compromised computer or another process running as the same user.
- **The symbol/audio channel:** session identifiers, sequence numbers, lengths, public machine fingerprints, timing, and ciphertext are exposed. The rotor checked protocol additionally exposes plaintext CRCs; `sealcrypt` does not transmit them. Acoustic transmissions can be recorded. No traffic-analysis protection is claimed.
- **An active sender or attacker:** `rotorcrypt` cannot prevent message injection, modification or forgery. `sealcrypt` authenticates each record against parties without the key, but shared-key possession does not identify an individual sender. Neither protocol prevents replay of a complete valid recording to a fresh receiver, denial of service, or deliberate suppression of messages. The 64-session in-memory duplicate caches are bounded stream bookkeeping, not durable replay prevention. A checked receiver may release intact later records after reporting missing content.
- **The local browser demo:** browser input and imported rotor key settings are passed to a local Python process. The browser and `er-demo` continue to demonstrate the rotor cipher; they do not expose `sealcrypt`. The demo is a trusted local tool, not a multi-user service or a remotely deployable application.

`sealcrypt keygen` generates random shared keys locally, but there is no identity system, authenticated key exchange, managed key distribution/rotation/revocation, forward secrecy, or secure deletion. Key holders must share keys through a separately trusted channel. Compromise of a shared key permits decryption of recorded sessions that used it. Production deployment requires review of the application protocol and its operational threat model.

## Public examples and private data

The [example key](examples/example-key.json), bundled key resource, example rotor catalog, and test settings are intentionally public. Demo defaults use these public values. `rotorcrypt` requires explicit machine and key paths so command-line users choose their settings deliberately; selecting the example file still uses a public key.

`sealcrypt` also requires explicit machine and key paths. Generate a fresh private key with `sealcrypt keygen --key secrets/seal-key.json`; it creates a mode-0600 file, creates missing parent directories with mode 0700, and refuses to overwrite an existing path. It does not print key material. Do not use public test fixtures as private keys or substitute a password for the required random key bytes.

Keep real key files under the ignored `secrets/` directory and set appropriate filesystem permissions. Git ignore rules do not encrypt files or prevent access by other programs. Do not commit live keys, credentials, `.env` files, private captures, or raw prompts containing secrets. Avoid putting private plaintext directly in `--text` when command-line argument exposure matters; use a protected file or pipe instead.

Terminal demos save plaintext, ciphertext, received symbols, recovered plaintext, recordings, and reports under ignored `tmp/demo/`. Browser jobs use temporary local directories for downloadable artifacts. Browser shutdown removes its temporary root during normal cleanup, but crashes can leave files behind. Browser downloads and user-created copies remain until the user removes them. These artifacts are not securely erased. Use synthetic messages when demonstrating the project.

If a secret is exposed, replace the affected settings and investigate the exposure. Deleting a file from the latest revision does not remove copies from Git history, recordings, caches, backups, or other machines.

## Browser demo protections and limitations

The server binds to IPv4 loopback, checks the expected Host and Origin, uses local static assets, and sends a restrictive content security policy. Configuration uploads are JSON data, not filesystem selectors or executable code. The browser does not intentionally persist key settings in local storage, send telemetry, or depend on cloud services.

Microphone capture begins only after a user action and browser permission. Stop, disconnect, and normal teardown release audio resources. The demo bounds text to 512 ASCII bytes, WAV uploads to 64 MiB, audio operations to ten minutes, and live PCM queues to two seconds; discontinuities produce errors rather than silent data loss. These bounds reduce accidental resource use, but the server is not designed to resist a hostile local user.

There is no server authentication. Anyone who can reach the loopback service in the same local environment is within its trust boundary. Do not expose it through a reverse proxy, port forwarding, container publication, or a public interface. Browser permissions and origin checks do not protect data from browser extensions, local malware, or a compromised account.

## Reporting a vulnerability

Report security issues privately to the maintainer, [@shanewiseman](https://github.com/shanewiseman). If GitHub's **Security → Report a vulnerability** option is available for this repository, use it. Otherwise, use a contact method the maintainer publishes on their profile to request a private reporting channel. If no private channel is available, open an issue containing only a request for a private security contact, without vulnerability details.

Do not disclose exploit details, private keys, credentials, personal information, or captured private traffic in a public issue. Include the affected revision, impact, prerequisites, a minimal reproduction using synthetic data, and any proposed mitigation. Do not test systems or transmit on radio equipment without appropriate authorization.

The maintainer will coordinate investigation and disclosure with the reporter. There is currently no guaranteed response time, security support period, or bug bounty. Hardware validation and human-keying reception evidence are tracked separately from simulated tests in the [validation record](docs/VALIDATION.md).
