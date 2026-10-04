# Architecture

## Current state

There is no application architecture yet. The repository contains documentation, AI contributor instructions, repository validation, and GitHub configuration. No radio transport, cryptographic protocol, application language, deployment topology, or hardware target has been selected.

The repository's validation tooling is infrastructure; its language does not select the application's implementation language.

## Repository map

| Location | Purpose |
| --- | --- |
| `AGENTS.md` | Repository-wide instructions for AI agents. |
| `docs/PROJECT.md` | Confirmed scope, constraints, and open product questions. |
| `docs/TASK_TEMPLATE.md` | Bounded prompts and verifiable acceptance criteria. |
| `docs/decisions/` | Accepted and superseded architecture decisions. |
| `docs/GITHUB.md` | GitHub configuration, protections, and administration. |
| `.github/` | Collaboration templates, automation, and GitHub configuration. |
| `scripts/` | Repository maintenance and validation tools. |

## Design record for the first implementation

Once requirements are accepted, extend this document with the information needed to review the actual system:

1. Components, responsibilities, interfaces, and external dependencies.
2. A data-flow diagram identifying sensitive data and trust boundaries.
3. Identity and key lifecycles, protocol choices, and the threat model.
4. Failure modes, recovery behavior, resource constraints, and observability.
5. Test boundaries, simulations, hardware testing, and integration environments.
6. Build, distribution, update, and operational ownership.

Clearly distinguish implemented behavior, accepted designs, and proposals. Link to [decision records](decisions/README.md) for choices and tradeoffs. Keep unaccepted alternatives out of implementation work unless the task explicitly requests an experiment.

Consult [SECURITY.md](../SECURITY.md) before security-sensitive work. Security or compliance claims require supporting evidence appropriate to the agreed environment.
