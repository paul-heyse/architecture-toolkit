# Agent handoff

## Establish context

Use the README setup commands, read the implementation contract and requirement index, and
inspect the working tree. Authorized maintainers should read the Notion links in ignored
`.context/workspace.json`; copy from the example only if that file is absent. Use the connected
Notion MCP in Cursor after authenticating. Do not commit authenticated exports or private URLs.
No GPU is required for this toolkit. Do not modify another document-processing environment.

## What works now

One locked Python 3.14 environment; a package/CLI; strict minimal model; endpoint checks;
version-pinned Delta → PyArrow → DataFusion adapter; synthetic examples; qualification tests;
checksummed local vendor bootstrap; source schema snapshot; docs; CI and this handoff.
`architecture build` is deliberately unavailable until the compiler is implemented.

## Implementation sequence

1. **Typed model and compiler.** Expand the registry, references, typed details, explicit Arrow
   schemas and profiles. Compile the synthetic model to normalized tables. Prove stable rename,
   relation type/direction checks, nested null/empty round trips, foreign keys and explicit unknowns.
   Cover DATA-03–14, 29–30, 41. Add a complete synthetic process, software and information slice.
2. **Coherent releases.** Add source digest, immutable manifest, single-writer lock, expected parent,
   staging/readback and current pointer. Prove failure after each stage never publishes a partial
   release, stale writers fail, unchanged versions are reused and retained releases still read.
   Cover DATA-19–25, 37, 39–40. Do not implement an append-only micro-edit event platform.
3. **Queries and changes.** Rebuild DataFusion catalog and NetworkX from the same manifest. Add
   parameterized queries, typed traversal policies, semantic diff and scenario comparison. Prove
   path explanations, isolation between releases, rename vs deletion, ordered-sequence changes,
   layout-only changes and separate status dimensions. Cover DATA-15–18, 26–29, 34, 38, 40.
4. **Notation generators and renders.** Generate ArchiMate, BPMN with DI, Structurizr C4, selective
   UML and actual-schema ERD. Prove IDs map back to source records and two views agree on the
   same elements. Qualify BPMN rendering locally; schema validation alone is insufficient. Preserve
   intentional layout separately. Cover DATA-30–31. Vendor fixtures are not generator tests.
5. **Release output and handover.** Build the local MkDocs bundle and self-contained milestone
   export; round-trip a historical release and a schema migration, then re-run all qualification
   checks on macOS ARM64 and Linux x86-64. Complete the requirement evidence index, document
   remaining gaps in Notion and retain versioned artifact provenance. Cover DATA-25, 35–42.

Start each step only once its dependencies are proven. The same programming agent can perform
all five in sequence; these are milestones within one project, not separate packages or handoffs.

## Done means

A reproducible synthetic vertical slice has source → storage → release → query → all planned
views, with fault-injection and historical-replay evidence, plus explicit limitations. Do not
mark the tool complete because a schema validates or a rendered image looks plausible.

## Checks

```sh
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run ty check src
uv run pytest
uv run python scripts/check_schema.py
uv run --group docs mkdocs build --strict
uv run python scripts/bootstrap_tools.py
uv run python scripts/qualify_tools.py
```

Dependency upgrades must regenerate the lock and pass interop tests on both target platforms.
Never enable native Delta/DataFusion FFI based only on an import succeeding.
