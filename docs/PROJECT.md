# Project brief

## Status

EncryptedRadio is a new project developed exclusively through LLM/AI prompts. The current repository establishes its working practices. The project name suggests an interest in encrypted radio communication, but it does not establish a product specification or security guarantee.

Maintainer: [@shanewiseman](https://github.com/shanewiseman). Default integration branch: `master`.

## Confirmed constraints

- Direct development through prompts with explicit objectives and reviewable acceptance criteria.
- Keep AI instructions and project decisions in version control.
- Use focused changes, repeatable checks, and evidence-backed review.
- Keep `master` protected with linear history and rebase integration, subject to the documented owner exception and the [GitHub configuration](GITHUB.md) being applied.
- Establish scope and security requirements before implementing a radio or cryptographic system.

## Decisions needed before implementation

| Area | Questions to resolve |
| --- | --- |
| Users and use cases | Who will use the system, in what environment, and what problem must it solve? |
| Product boundary | Is this software, firmware, hardware, a simulator, or some combination? |
| Radio platform | Which hardware, bands, modulation, transport, and interoperability requirements apply? |
| Operating constraints | What jurisdiction, licensing, permitted operating modes, power limits, and encryption restrictions apply to the intended use? |
| Security | What assets and adversaries matter, and what properties must be demonstrated? |
| Key lifecycle | How are identities and keys provisioned, protected, rotated, revoked, and recovered? |
| Implementation | Which language, toolchain, dependencies, and target platforms are appropriate? |
| Quality | What latency, reliability, resource, interoperability, and test requirements define acceptance? |
| Delivery | How will builds, updates, releases, and support be managed? |
| License | Which license and contribution terms should the project adopt? |

These questions are intentionally unanswered. A prompt must not silently turn an assumption into a requirement.

## First implementation gate

Before introducing an application skeleton or selecting application dependencies, accept a bounded initial use case, identify its platform and testing environment, and record relevant architecture and security decisions. Start with a testable increment that satisfies the agreed scope.

Track concrete work in issues or pull requests using [TASK_TEMPLATE.md](TASK_TEMPLATE.md). Record consequential accepted decisions in [decisions/](decisions/README.md), and update this brief when scope changes.
