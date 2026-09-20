# Architecture toolkit

A reusable architecture-as-code **foundation for implementation**. Author a typed model once,
then produce consistent architecture, process, software and data views. The full compiler,
release manager and projection generators remain to be built; this repository makes their
contracts, environment and acceptance work concrete.

## Start here

```sh
uv python install 3.14.7
uv sync --locked --all-groups
uv run architecture doctor
uv run architecture validate examples/minimal/model.yaml
uv run pytest
uv run python scripts/bootstrap_tools.py
uv run python scripts/qualify_tools.py
uv run --group docs mkdocs build --strict
```

Use uv 0.12.7. Install Graphviz (`dot`) using the platform package manager before tool
qualification. All Python commands share **one project, one lockfile and one `.venv`**.
Vendor Java tools live under ignored `.tools/`; they do not create another Python project.
Supported qualification targets: macOS ARM64 and Linux x86-64, Python 3.14.

- [Agent handoff](docs/agent-handoff.md): what to implement next and how to prove it.
- [Implementation contract](docs/implementation-contract.md): boundaries and milestones.
- [Toolchain](docs/toolchain.md): downloads, hashes, local execution and upgrades.
- [Qualification](docs/qualification.md): verified scope and compatibility limitations.
- [Public references](docs/references.md) and [acceptance index](reference/requirements.json).

## Workspace responsibilities

Git contains reusable code, schemas, synthetic examples, tests and operational documentation.
Narrative design, research and decisions remain in the connected Notion workspace. Authorized
maintainers can copy `.context.example.json` to `.context/workspace.json` and add private
Notion/Dropbox locations there. That ignored file is deliberately absent from public Git.
Cursor's optional Notion MCP configuration requires the user's own sign-in; no access token
is included. External contributors can work against the public contracts without that access.

Compiled Delta tables and release staging belong in host-local `.runtime/`. Dropbox can
receive intentional dated, self-contained exports; never put a live Delta store or `.venv`
in a sync folder. Consumer projects keep their models and evidence outside this public repo.

## Status and licensing

`validate` checks only the experimental minimal schema, identities and endpoints.
`build` deliberately exits with an unimplemented error. Passing tests are foundation evidence,
not proof of a complete modeling tool or of real-world architecture correctness.

This public repository currently has no project license grant. A maintainer must choose a
license before presenting it as licensed open-source software or distributing a release.
Third-party tools retain their own licenses; see [notices](THIRD_PARTY_NOTICES.md).
