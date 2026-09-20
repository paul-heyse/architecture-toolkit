# Architecture toolkit

Reusable architecture-as-code foundation: author a typed canonical model, publish coherent
versioned releases, query the same release relationally and as a graph, then generate traceable
architecture/process/software/data projections and an offline documentation bundle.

The full compiler and release/projection pipeline are not yet implemented. This repository defines
the executable contracts and qualification boundaries for building them.

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

Use uv 0.12.7. All Python commands share **one project, one lockfile and one `.venv`**.
Vendor runtimes stay under ignored `.tools/`; generated/local runtime data stays under
ignored `.runtime/`. Supported qualification targets are macOS ARM64 and Linux x86-64.

## Contracts

- [Implementation contract](docs/implementation-contract.md): global invariants and contract map.
- [Core contract](docs/contracts/core.md): Pydantic, YAML, diagnostics, NetworkX, Jinja/lxml,
  Hypothesis/pytest, Pyrefly target and Ruff.
- [Data contract](docs/contracts/data.md): Arrow/DataFusion/deltalake, releases, queries and history.
- [Projection contract](docs/contracts/projections.md): ArchiMate, C4, BPMN, UML/ERD, rendering
  and offline publishing.
- [Agent handoff](docs/agent-handoff.md): dependency-ordered implementation sequence.
- [Qualification](docs/qualification.md): what this commit actually proves.
- [Toolchain](docs/toolchain.md): current and target library/vendor execution state.
- [Acceptance index](reference/requirements.json): DATA-01..60, PROJ-01..42, CORE-01..67.

## Workspace responsibilities

Notion owns full design rationale, research, decisions, questions and work state. Git owns
reusable implementation contracts, schemas, code, configuration, tests and runbooks.
Authorized maintainers may copy `.context.example.json` to ignored
`.context/workspace.json` and populate private workspace URLs locally. Never commit those URLs.

Compiled Delta stores, staging data and caches remain host-local. Dropbox or another delivery
location may receive intentional dated self-contained exports, never a live database or `.venv`.
Consumer-specific models/evidence live outside this public repository.

## Current state

Implemented today: one locked Python 3.14 environment, minimal strict domain model and CLI,
version-pinned Delta -> PyArrow -> DataFusion fallback adapter, synthetic examples, basic
qualification tests, local vendor bootstrap and handwritten vendor smoke fixtures.

Not implemented today: the full metamodel/compiler, coherent multi-table releases, advanced
snapshot providers, semantic diff, graph policies, generated standards projections, interactive
portal, requirement-evidence plugin, or the Pyrefly migration. D-032 selects Pyrefly as the
**target** checker; the current repository still executes ty.

Passing tests establish only their stated scope and never prove real-world architecture accuracy.

This repository currently has no project license grant. Third-party materials retain their own
licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
