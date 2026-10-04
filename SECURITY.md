# Security policy

## Current status

EncryptedRadio implements an experimental Enigma-style rotor cipher, a checked symbol protocol, and Morse audio demonstrations. It does **not** provide modern cryptographic security, authenticated encryption, or a supported production communications system. Passing tests establish specific functional behavior; they are not cryptanalysis, a security audit, or evidence of protection against a capable adversary.

The custom rotor construction was explicitly selected for this educational/experimental application. CRC32 checks detect accidental transmission damage and many incorrect-key results. An attacker can recompute them. The SHA-256 block-offset derivation and public machine fingerprint do not authenticate messages or turn the rotor cipher into modern encryption.

## Threat model and boundaries

The implemented checked protocol targets accidental loss, corruption, duplication, and reordering on a single foreground audio channel. It validates complete blocks before releasing their plaintext and can resume with subsequent valid blocks. Raw mode deliberately lacks these checks and can silently produce incorrect output after symbol damage.

The assets are plaintext, private rotor settings, and locally generated recordings. Their relevant boundaries are:

- **Local files and processes:** private configurations and plaintext are visible to the invoking account and processes able to access their files, memory, terminal, or command-line arguments. The application does not defend against a compromised computer or another process running as the same user.
- **The symbol/audio channel:** session identifiers, sequence numbers, lengths, public machine fingerprints, plaintext CRCs, timing, and ciphertext are exposed. Acoustic transmissions can be recorded. No traffic-analysis protection is claimed.
- **An active sender or attacker:** message injection, modification, forgery, replay across restarts, denial of service, and deliberate session disruption are outside the protocol's security guarantees. The 64-session in-memory duplicate cache is operational bookkeeping, not authentication or durable replay prevention.
- **The local browser demo:** browser input and imported key settings are passed to a local Python process. The demo is a trusted local tool, not a multi-user service or a remotely deployable application.

There is no identity system, authenticated key exchange, managed key generation/rotation/revocation, forward secrecy, or secure deletion. Reusing settings or publishing ciphertext does not imply any quantified security strength. Use a reviewed authenticated-encryption design and a new threat model if an application needs confidentiality or authenticity against adversaries.

## Public examples and private data

The [example key](examples/example-key.json), bundled key resource, example rotor catalog, and test settings are intentionally public. Demo defaults use these public values. `rotorcrypt` requires explicit machine and key paths so command-line users choose their settings deliberately; selecting the example file still uses a public key.

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
