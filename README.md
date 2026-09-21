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
uv run architecture --help                                   # every verb
uv run architecture doctor
uv run architecture validate examples/minimal/model.yaml
uv run pytest
uv run python scripts/bootstrap_tools.py
uv run python scripts/qualify_tools.py
uv run --group docs mkdocs build --strict
```

The full command surface is generated into [docs/cli.md](docs/cli.md).

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
- [Implementation plans](docs/plans/index.md): M1..M6 decomposed into executable waves W0..W9,
  with a machine-checked requirement partition in `reference/plan-waves.json`.
- [Qualification](docs/qualification.md): what this commit actually proves.
- [Contract enforcement](docs/contract-enforcement.md): how contract rules are made
  executable, and the parser/syntax-tree/text tiers.
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

Implemented today: one locked Python 3.14 environment; the strict Pydantic domain model with typed
detail records, change commands and generated JSON Schema contracts; ruamel round-trip authoring
with source-located diagnostics; the twelve-table Arrow fabric and its `SnapshotProvider` ladder;
coherent Delta-backed releases with an immutable manifest, the eight-step publication protocol,
retention and milestone archives; release-scoped DataFusion query recipes and the private NetworkX
graph facade with versioned policies; semantic change records with a total classification table,
design-alternative identity and the DATA-38 lifecycle; a Typer CLI whose reference is generated
into [docs/cli.md](docs/cli.md); requirement-evidence output; and the Pyrefly migration, enforced
at 100% strict coverage over `src/`.

Not implemented today: generated ArchiMate/C4/BPMN/UML/ERD projections, the rendering pipeline and
the interactive portal. `architecture build` and `architecture output` are reserved for those waves
and say so when run; [docs/plans/index.md](docs/plans/index.md) says which wave fills each.

Everything above waves 0 and 1 is evidenced on macOS ARM64 only. Those two waves passed the Linux
runner through pull requests; the branches for waves 2 through 6 are pushed and have had no CI run,
so no claim here is yet a cross-platform claim.

Passing tests establish only their stated scope and never prove real-world architecture accuracy.

This repository currently has no project license grant. Third-party materials retain their own
licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
