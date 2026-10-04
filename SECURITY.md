# Security policy

## Current status

EncryptedRadio has no supported software releases or implemented security guarantees yet. Repository checks are not a cryptographic review. Do not use this repository as a production communications or security system.

## Reporting a vulnerability

Report security issues privately to the maintainer, [@shanewiseman](https://github.com/shanewiseman). If GitHub's **Security → Report a vulnerability** option is available for this repository, use it. Otherwise, use a contact method the maintainer publishes on their profile to request a private reporting channel. If no private channel is available, open an issue containing only a request for a private security contact, without vulnerability details.

Do not disclose exploit details, private keys, credentials, personal information, or captured private traffic in a public issue. Include the affected revision, impact, prerequisites, minimal reproduction using synthetic data, and any proposed mitigation in the private report. Do not test systems or transmit on radio equipment without appropriate authorization.

The maintainer will coordinate investigation and disclosure with the reporter. There is currently no guaranteed response time, security support period, or bug bounty.

## Design requirements to establish

Before implementing security-sensitive functionality, document and review:

- Assets, adversaries, trust boundaries, intended use, and out-of-scope threats.
- Key generation, provisioning, storage, rotation, revocation, recovery, and destruction.
- Authentication, confidentiality, integrity, replay handling, and failure behavior.
- The choice of established protocols and maintained cryptographic libraries.
- Metadata exposure, logging, telemetry, and retention of sensitive information.
- Dependencies, update mechanisms, and verification appropriate to the target hardware.
- The jurisdiction, bands, operating modes, and constraints relevant to intended radio use.

These are open design questions, not implemented capabilities. Record accepted decisions in [architecture decision records](docs/decisions/README.md). Require suitable expert review before claiming security properties or deploying security-sensitive features.

## Secret handling

Use placeholders in examples and synthetic secrets in tests. Never commit live keys, credentials, `.env` files containing secrets, or sensitive captures. If a secret is exposed, revoke or rotate it promptly; deleting it from the latest revision does not remove it from history.
