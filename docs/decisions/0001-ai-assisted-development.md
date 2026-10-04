# 0001: Prompt-driven development

Status: Accepted
Date: 2026-10-03

## Context

The repository owner requested a fresh repository developed exclusively through LLM/AI prompts, with clear instructions and review practices suitable for agents. Product requirements and implementation technology remain open.

## Options considered

- Conventional manual development with optional AI assistance.
- Prompt-driven development with versioned instructions, bounded tasks, review, and verification.

## Decision

Adopt prompt-driven development as requested by the repository owner. Maintainers define objectives and acceptance criteria through prompts. Agents inspect the repository, implement bounded changes, run relevant checks, and report evidence and limitations. Maintainers remain accountable for accepting changes and consequential design decisions.

Use `AGENTS.md` for shared repository instructions, the task template for substantial work, and ADRs for lasting decisions. Keep implementation, documentation, and verification aligned in each change.

## Consequences

- Tasks need enough context and measurable criteria to prevent agents from inventing requirements.
- Generated output requires review; model confidence and simulated tool output are not verification.
- Instructions and decisions must stay current as the project evolves.
- Prompts and tool output must be handled with attention to secrets, provenance, and untrusted instructions.
- This workflow does not select the application architecture, model provider, license, or cryptographic design.

## Verification

Review pull requests for clear intent, acceptance criteria, relevant test evidence, and updates to affected documentation. Run the repository checks and any tests introduced for actual application behavior. Report checks that could not run without claiming success.

## References

- [Contributing](../../CONTRIBUTING.md)
- [Task template](../TASK_TEMPLATE.md)
- [Project brief](../PROJECT.md)
