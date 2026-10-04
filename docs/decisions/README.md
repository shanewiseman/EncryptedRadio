# Architecture decision records

Use architecture decision records (ADRs) for choices with lasting consequences, such as product boundaries, hardware, languages, protocols, cryptographic libraries, dependency policy, release design, or licensing. Routine edits do not need an ADR.

Create a numbered Markdown file such as `0002-select-initial-platform.md`. Keep each record focused on one decision. Start as **Proposed** and change to **Accepted** only after the maintainer accepts the decision. Do not rewrite history when a decision changes: add a new record and mark the old one **Superseded by ADR NNNN**. Rejected proposals may remain as **Rejected** when preserving the reasoning is useful.

## Template

```markdown
# NNNN: Decision title

Status: Proposed
Date: YYYY-MM-DD

## Context

Describe the problem, requirements, constraints, and supporting evidence.

## Options considered

Compare the relevant alternatives and their tradeoffs.

## Decision

State the selected option and who accepted it. For a proposal, state what remains to be decided.

## Consequences

Describe benefits, costs, risks, compatibility implications, and follow-up work.

## Verification

Describe how the decision's assumptions and intended properties will be checked.

## References

Link relevant issues, pull requests, specifications, or research.
```

## Index

- [0001: Prompt-driven development](0001-ai-assisted-development.md) — Accepted.
- [0002: Rotor cipher, replaceable Morse transport, and working demos](0002-rotor-morse-suite.md) — Accepted.
- [0003: Authenticated replacement cipher command](0003-authenticated-sealcrypt.md) — Accepted.

ADRs 0002 and 0003 are complementary: the rotor application and its terminal/browser
demonstrations remain implemented, while `sealcrypt` adds a separate authenticated
CLI and protocol over the same transport. ADR 0003 does not retroactively add
authentication to rotor ciphertext or replace the original decision record.
