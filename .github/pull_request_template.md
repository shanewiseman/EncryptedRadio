## Purpose

Describe the requested outcome and link the issue or summarize the originating prompt.
Remove secrets and private context from prompt summaries.

## Changes

Describe the resulting behavior and any material design decisions.
Identify affected commands (`rotorcrypt`, `sealcrypt`, `morselink`, `audiolink`, `er-demo`), browser
operations, or repository tooling. For data-path changes, state modes/profiles,
input sources, and any CLI, configuration, or wire compatibility impact.

## Acceptance and validation

- [ ] The requested acceptance criteria are met.
- [ ] `make check` passes.
- [ ] Relevant behavior is verified; commands and results are recorded below.
- [ ] Documentation and decisions reflect the change where needed.
- [ ] No credentials, private prompt logs, or unlicensed material are included.

Record actual results, limitations, and anything not tested. An AI assertion is
not test evidence.

Run `make demo` for data-path changes; it defaults to the rotor/Morse pipeline.
Record checked/raw verification for every affected cipher/transport combination. Note skipped checks
(including browser lifecycle checks without Node.js) and distinguish WAV/mocked
audio evidence from physical microphone or human-keying acceptance. Use synthetic
input and public demo settings; never include private keys or captured private traffic.

## Risks and follow-up

Describe compatibility, security, migration, or rollback concerns when relevant.
Use **Rebase and merge** after required checks and review; keep commits focused.
