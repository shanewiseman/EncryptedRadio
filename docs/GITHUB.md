# GitHub administration

The desired policy for `shanewiseman/EncryptedRadio` is stored in
[repository.json](../.github/repository.json) and the two
[rulesets](../.github/rulesets/). GitHub does **not** apply these files merely
because they are committed. Apply them with the administrator script below, or
configure the equivalent settings in GitHub's repository settings.

## Branch and review policy

`master` is the default branch. Two independent, active rulesets target it:

| Ruleset | Required behavior | Bypass |
| --- | --- | --- |
| `managed-master-integrity` | Linear history; no force pushes; no branch deletion | Nobody, including the owner |
| `managed-master-collaboration` | PR; one code owner approval; approval after the latest push; stale approval dismissal; resolved review threads; current `Repository checks` success | Only `@shanewiseman` (GitHub user ID `8761990`) |

The owner can push directly or bypass the collaboration rules. The owner still
cannot introduce merge commits, force-push, or delete `master` while the integrity
ruleset is active. Administrators can edit repository settings; rulesets are not a
control against an administrator changing the policy itself. Other contributors
need a PR and owner review. Bots receive no bypass.

GitHub's **Rebase and merge** operation is the only enabled PR integration method.
Merge commits and squash merging are disabled both by repository settings and the
PR rule. Ordinary fast-forward pushes by the owner remain permitted; GitHub cannot
prove a linear commit was produced by a particular local command. Rebase feature
branches onto the latest `master`, resolve conflicts, and rerun checks.

`Repository checks` is the exact CI job name. Its required check is bound to the
GitHub Actions app (integration ID `15368`), and the branch must be current with
`master` before integration. Renaming the CI job requires updating the ruleset.
Human owner review remains necessary: the job alone does not prove that a proposed
workflow change is trustworthy.

The [CI workflow](../.github/workflows/ci.yml) installs uv, the locked Python audio
and demo extras, and the PortAudio runtime on Ubuntu. It runs `make check`
(repository hygiene and application tests) followed by `make demo` (the actual
rotor cipher/WAV round trip). Tests include sealcrypt's authenticated protocol;
`make demo` remains a rotor demonstration. Browser lifecycle tests need Node.js
and report a skip if it is unavailable. See [validation](VALIDATION.md) for the
full reproduction commands and the distinction between synthetic and hardware
evidence. These jobs do not validate physical speaker/microphone reception or a
human operator.

## Repository defaults

- Delete feature branches after PR integration; disable automatic merging.
- Enable issues; disable unused wikis, projects, and discussions.
- Enable Actions, require full commit SHA pins, and default workflow tokens to
  read access. Workflows cannot approve PRs with their default token.
- Enable Dependabot vulnerability alerts and the dependency graph.
- Enable private vulnerability reporting when the repository is public; this
  feature is not applicable to private repositories.

Repository visibility, collaborators, licensing, paid security products, and
unrelated existing rulesets are not managed by the script.

## Apply and verify

Install the locked environment, then run the offline repository and application
checks first. Use the [installation prerequisites](../README.md#install-and-run),
including Node.js 18+ for full browser lifecycle coverage:

```sh
make sync
make check
```

The GitHub repository must already exist and contain an initial `master` branch.
Push the reviewed initial commit and allow its `Repository checks` workflow to run
before applying the required-check rule. Branch rulesets are available for public
repositories on GitHub Free and for private repositories on eligible paid plans.
The script reports API failures rather than weakening a rule to fit the plan.

Authenticate locally as an administrator using `gh auth login`, or supply
`GH_TOKEN` (preferred) or `GITHUB_TOKEN` through the process environment. A
fine-grained token needs access to this repository, **Administration: write** and
**Contents: read**; metadata read is implicit. The write permission is also needed
for a complete audit because GitHub omits bypass actors from insufficiently
privileged responses. Do not commit a token or pass it as a command-line argument.

```sh
# Read-only; this is also the default when no flag is supplied.
python3 scripts/configure_github.py --check

# Explicitly apply the checked-in policy, then read it back for verification.
python3 scripts/configure_github.py --apply

# Check again whenever settings or policy files change.
python3 scripts/configure_github.py --check
```

Exit codes are `0` for a matching or successfully applied policy, `1` for drift in
check mode, and `2` for configuration, authorization, network, or verification
errors. The script preflights managed state before writing, updates rulesets by
their unique names, and preserves unrelated rulesets. Duplicate managed names
abort the run. Renaming a managed ruleset file's `name` creates a new ruleset;
remove an obsolete remote ruleset deliberately after reviewing its effect.

REST writes are not transactional. If a request fails mid-application, earlier
changes may already have applied. Fix the cause and rerun `--check`, then
`--apply`; the process is idempotent. The script never silently replaces the
owner-specific bypass with a role-wide administrator bypass.

CI downloads dependencies during setup, then runs checks and a WAV demonstration
without audio hardware or remote application services. It has no administrative
token and never applies policy files from a PR. To inspect or apply remote
settings, run the script locally from a trusted checkout.

## References

- [GitHub ruleset API](https://docs.github.com/en/rest/repos/rules)
- [Available rules and plan support](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- [Repository settings API](https://docs.github.com/en/rest/repos/repos)
- [Actions permissions API](https://docs.github.com/en/rest/actions/permissions)

The API version is pinned to `2026-03-10`. The owner's numeric ID and the GitHub
Actions integration ID were verified against GitHub's API during initialization.
