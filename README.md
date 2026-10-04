# EncryptedRadio

EncryptedRadio is a new, prompt-driven project. Its product requirements, target hardware, radio protocols, implementation language, and cryptographic design have not yet been selected. This repository currently provides development guidance and repository checks; it does not implement an encrypted radio system.

## Start here

1. Read [AGENTS.md](AGENTS.md) for instructions that apply to AI agents and contributors.
2. Read the [project brief](docs/PROJECT.md) and [architecture record](docs/ARCHITECTURE.md) before proposing implementation work.
3. Define a bounded task with the [task template](docs/TASK_TEMPLATE.md), including acceptance criteria and how they will be verified.
4. Follow [CONTRIBUTING.md](CONTRIBUTING.md) and run `make check` before submitting changes.

Development is directed through LLM/AI prompts. Maintainers choose the objectives, assess evidence, and remain accountable for the code and its consequences. Generated output receives the same review as any other contribution.

## Local baseline

The repository checks require Python 3.12+ and Make, and use only Python's standard library. These are repository tooling requirements; the application's runtime has not been selected. From the repository root:

```sh
make check
```

These checks validate the repository baseline. They do not establish application correctness, cryptographic security, hardware compatibility, or regulatory compliance. There is no application build, installation procedure, or supported release yet.

Repository administrators can inspect the GitHub configuration with:

```sh
python3 scripts/configure_github.py --check
```

See [GitHub configuration](docs/GITHUB.md) for authentication, permissions, and applying the settings defined in `.github/repository.json` and `.github/rulesets/`.

## Project records

- [Project scope and open questions](docs/PROJECT.md)
- [Architecture and security design status](docs/ARCHITECTURE.md)
- [Architecture decision records](docs/decisions/README.md)
- [GitHub configuration](docs/GITHUB.md)
- [Change history](CHANGELOG.md)
- [Security reporting](SECURITY.md)
- [Support](SUPPORT.md)
- [Code of conduct](CODE_OF_CONDUCT.md)

## License

No license has been selected. This repository does not grant a license to use, modify, or distribute its contents. A maintainer must make and document the licensing decision before publishing a licensed release.
