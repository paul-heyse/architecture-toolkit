# Qualification scope

This file describes evidence for the **current repository**, not target architecture.

## Current evidence matrix

| Layer | Proven now | Target | State |
| --- | --- | --- | --- |
| CORE domain | minimal strict Pydantic model, unique IDs, endpoint checks | CORE-01..67 | partial |
| YAML | configured 1.2 round-trip profile, forbidden constructs with stable codes, SourceMap, source-located diagnostics with a stated resolution, command-driven round-trip editing and a presentation-invariance property (W2) | authored-order semantics for W5/W6 traversal | proven for M1 |
| Static typing | Pyrefly over src/tests/scripts, 0 errors; strict `src` coverage 100.00%; `pyarrow-stubs` qualified statically and at run time with two divergences pinned | D-032 / Pyrefly CORE-53..62 | migrated; coverage floor 98 |
| DATA Arrow/Delta | nested interface, nullable scalar, empty table, explicit Arrow schema, Delta history | DATA-01..60 | partial |
| Snapshot provider | explicit-version materialized PyArrow registration | materialized fallback + qualified Dataset/stream candidates | partial |
| DataFusion | scalar SQL binding over pinned snapshot | release-scoped catalogs/query recipes/plan evidence | partial |
| NetworkX | parallel MultiDiGraph edges preserved | private GraphPolicy facade/explainable analyses | partial |
| Release publication | none | coherent manifest/lock/staging/failure protocol | pending |
| Semantic diff/migration | versioned canonical hash and record-level delta over added, removed and changed identities (W2) | typed change classification, scenarios, historical migrations | partial |
| PlantUML | handwritten ArchiMate fixture renders SVG | generated ArchiMate/UML/ERD with provenance/security | scaffold only |
| Structurizr | handwritten DSL validates/exports | generated explicit-ID C4 + rich static export | scaffold only |
| BPMN | handwritten XML validates against local OMG XSD | generated semantic/DI/moddle/lint/layout/bpmn-js pipeline | scaffold only |
| Portal | strict basic MkDocs build | offline generated portal + rich C4/BPMN | scaffold only |
| Requirement evidence | legacy v1 DATA-only index on the base scaffold | 169-requirement v2 index + generated evidence | docs update |

## Known DataFusion / deltalake limitation

On 2026-09-20, deltalake 1.6.4's direct provider targeted a different DataFusion major than the
repository's DataFusion 54 lock. Presence of a provider API did not imply binary compatibility.

The current fallback opens an explicit Delta version, materializes it to PyArrow record batches and
registers those batches in DataFusion while preserving empty-table schema. Native FFI remains
disabled. Dataset/stream alternatives are target capabilities, not passing evidence.

## Current vendor smoke checks

`scripts/qualify_tools.py` validates only:
- handwritten PlantUML ArchiMate fixture -> SVG;
- handwritten Structurizr workspace -> validate/export;
- handwritten BPMN XML -> OMG XSD.

It does not prove:
- canonical-model projection generation;
- ArchiMate semantic relationship validity or Exchange import;
- C4 identity/membership parity;
- BPMN semantic correctness beyond XSD;
- BPMN browser rendering/layout;
- portal integration.

## Target evidence model

`reference/requirements.json` defines static requirement statements. Future pytest qualification
emits a separate machine-readable evidence artifact validated by
`schemas/qualification-evidence.schema.json`.

Do not hand-edit a requirement to “passed” because one partial test exists.

## Still to prove

- CORE-01..67 implementation, including source-aware diagnostics;
- DATA-01..60 coherent release/query/history architecture;
- PROJ-01..42 generated standards projections and portal;
- full synthetic vertical slice;
- publication fault injection and stale-parent behavior;
- historical replay and schema migration;
- both-platform qualification for all affected dependency/tool families;
- real-world architecture/evidence correctness and consumer acceptance.

The repository's Actions/check results on a specific commit are the execution evidence; this page is
a scope statement, not a permanent certification.
