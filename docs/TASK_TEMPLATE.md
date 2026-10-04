# Task template

Copy and complete this template when prompting an agent for substantial work. Remove sections that do not apply; write `Not applicable` where that distinction matters. Link existing decisions instead of duplicating them. Never include secrets or sensitive personal data.

## Objective

What concrete outcome should this task produce, and why is it needed?

## Context

Identify relevant files, issues, accepted decisions, current behavior, and any prior evidence. Instruct the agent to read `AGENTS.md` and applicable directory instructions before editing.

## Scope

- In scope:
- Out of scope:
- Constraints and compatibility requirements:
- Decisions already accepted:
- Assumptions to verify or questions to resolve:

## Acceptance criteria

Use observable outcomes rather than vague goals such as "production ready."

- [ ] Given a specific condition, the expected behavior or artifact is observable.
- [ ] Relevant failure cases are handled and verified.
- [ ] Affected documentation and decision records reflect the final result.

## Verification

Specify the commands, scenarios, or review evidence needed to establish acceptance. Include `make check` for repository changes and behavior-specific checks where applicable. Identify any unavailable hardware, credentials, network access, or other test prerequisites.

## Security and external effects

Identify sensitive data, trust boundaries, dependency changes, hardware use, external service changes, or irreversible operations relevant to this task. State any restrictions or already-authorized actions. Resolve material security or product ambiguity before dependent implementation.

## Completion report

Ask the agent to report the resulting behavior, files changed, checks actually run and their results, and material limitations or remaining decisions. Require a clear distinction between completed work and proposed follow-up work.
