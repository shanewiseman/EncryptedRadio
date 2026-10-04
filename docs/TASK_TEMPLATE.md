# Task template

Copy and complete this template when prompting an agent for substantial work. Remove sections that do not apply; write `Not applicable` where that distinction matters. Link existing decisions instead of duplicating them. Never include secrets or sensitive personal data.

## Objective

What concrete outcome should this task produce, and why is it needed?

## Context

Identify relevant files, issues, accepted decisions, current behavior, and any prior evidence. Instruct the agent to read `AGENTS.md` and applicable directory instructions before editing.

Identify the affected command (`rotorcrypt`, `sealcrypt`, `morselink`, or `er-demo`),
browser operation, or repository tooling. For data-path work, state the cipher
mode/Morse profile and whether input arrives as complete text, a file, streaming
stdin, WAV, or live PCM. Browser and terminal demos currently use the rotor cipher.

## Scope

- In scope:
- Out of scope:
- Constraints and compatibility requirements:
- Decisions already accepted:
- Assumptions to verify or questions to resolve:

For cipher or transport changes, include CLI and wire compatibility requirements.
Read `docs/PROTOCOL.md` for the rotor protocol, `docs/SEALCRYPT.md` for authenticated
records, and `docs/ARCHITECTURE.md` for shared-code and transport boundaries.

## Acceptance criteria

Use observable outcomes rather than vague goals such as "production ready."

- [ ] Given a specific condition, the expected behavior or artifact is observable.
- [ ] Relevant failure cases are handled and verified.
- [ ] Affected documentation and decision records reflect the final result.

## Verification

Specify the commands, scenarios, or review evidence needed to establish acceptance. Include `make check` for repository changes and behavior-specific checks where applicable. Identify any unavailable hardware, credentials, network access, or other test prerequisites.

Use `make sync` to install locked dependencies. Full browser lifecycle coverage
also needs Node.js 18+. Run `make demo` after data-path changes; it verifies the
rotor pipeline, so sealcrypt changes additionally need their own checked/raw
round trips. Select relevant failures such as invalid input, damaged/missing
records, authentication failure, truncated EOF, broken pipes, or audio
discontinuities. Record skipped checks explicitly. Keep offline/mock evidence
separate from physical audio and human-keying acceptance in `docs/VALIDATION.md`.

## Security and external effects

Identify sensitive data, trust boundaries, dependency changes, hardware use, external service changes, or irreversible operations relevant to this task. State any restrictions or already-authorized actions. Resolve material security or product ambiguity before dependent implementation.

Use synthetic plaintext and public demo configuration in shared evidence; never
include real private keys or captured private traffic. For sealcrypt changes,
preserve nonce uniqueness and authentication before plaintext release in both
modes. Rotorcrypt remains experimental and its CRCs do not authenticate messages.

## Completion report

Ask the agent to report the resulting behavior, files changed, checks actually run and their results, and material limitations or remaining decisions. Require a clear distinction between completed work and proposed follow-up work.
