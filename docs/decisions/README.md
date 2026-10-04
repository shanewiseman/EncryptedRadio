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
- [0004: Packet audio and composable demonstrations](0004-packet-audio-and-composable-demos.md) — Accepted.
- [0005: Optional lowercase-first encoding](0005-lowercase-first-encoding.md) — Defaults superseded by ADR 0006; wire encoding retained.
- [0006: Lowercase-first by default](0006-default-lowercase-first.md) — Accepted.

ADRs 0002, 0003 and 0004 are complementary. The rotor and Morse implementations
remain available. Sealcrypt adds its own authenticated protocol; audiolink adds a
separate packet audio transport. The terminal and browser select either cipher
and transport without changing their security properties. Later additions do not
retroactively authenticate rotor ciphertext or rewrite the original decisions.
