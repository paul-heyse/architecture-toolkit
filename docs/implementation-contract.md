# Implementation contract

## Authority

This repository contains executable architecture contracts. Full rationale, research and decisions
remain in the authorized Notion workspace. Refer to stable record IDs (for example
`ARCH-TOOL-DATA-001`, `ARCH-TOOL-PROJ-001`, `ARCH-TOOL-CORE-001`, D-030..D-032)
without copying private workspace URLs or private content into Git.

## Global invariants

1. One canonical typed architecture model. Stable IDs are independent of display names.
2. YAML/JSON, Arrow/Delta, NetworkX, notation files, rendered diagrams and portal pages are
   representations of that model, not independent semantic sources.
3. Pydantic owns domain/runtime validation; Arrow owns physical tabular schemas.
4. Delta table versions are storage history. `ArchitectureRelease` owns coherent multi-table state.
5. Published releases never resolve an implicit latest table version.
6. DataFusion and NetworkX are reconstructed from the same selected release.
7. NetworkX is disposable analytical state; the raw graph is not durable storage.
8. Domain mutation is command-driven and separate from read/query APIs.
9. View semantics, notation mapping, layout and rendered bytes are separate concerns.
10. Generated projections never invent canonical relationships, workflow behavior or data schema.
11. Unknown/not-applicable/withheld/evidence-gap states remain explicit.
12. Application implementation is Python-only: one uv project, lock and environment.
13. Confidential models render locally by default; no public renderer is a default destination.
14. Notion owns design narrative/state; Git owns executable contracts and evidence mechanisms.
15. The client/consumer need not adopt this toolkit.

## Contract map

| Concern | Normative contract | Requirements |
| --- | --- | --- |
| Domain, authoring, graph, generation, engineering qualification | [core.md](contracts/core.md) | CORE-01..67 |
| Storage, query, releases, history | [data.md](contracts/data.md) | DATA-01..60 |
| Standards projection, rendering, publishing | [projections.md](contracts/projections.md) | PROJ-01..42 |

`reference/requirements.json` is the machine-readable acceptance index. Requirement definitions
are static contracts; test outcomes are generated evidence, not hand-maintained status fields.

## Package boundaries

| Path | Responsibility |
| --- | --- |
| `domain` | IDs, typed domain/commands/manifests, registries, profiles |
| `validation` | diagnostics, record/cross-record rules, validator adapters |
| `storage` | Arrow schemas/mappings, Delta persistence, SnapshotProvider adapters |
| `queries` | release-scoped DataFusion recipes and NetworkX graph policies |
| `releases` | manifest, semantic diff, migration, lock/staging/publication |
| `projections` | ArchiMate, BPMN, Structurizr, UML/ERD generators |
| `rendering` | bounded local vendor adapters and render provenance |
| `publishing` | offline MkDocs bundle and self-contained exports |
| `profiles` | versioned generic/consumer extensions; no embedded client model |
| `schemas` | generated authoring schemas and public contract schemas |
| `tests` | unit/property/integration/interop/qualification evidence |
| `reference` | acceptance index and public source catalog |

## Canonical flow

```text
authoring source
 -> source map + strict Pydantic domain
 -> cross-record validation
 -> immutable candidate
 -> explicit Arrow tables
 -> version-pinned Delta snapshots
 -> immutable ArchitectureRelease manifest
 -> release-scoped DataFusion + disposable NetworkX
 -> semantic diff / query / impact
 -> notation projection sources
 -> local renders + offline portal + milestone export
```

## Dependency order

1. CORE domain/authoring/diagnostic contracts.
2. DATA physical schemas, storage and coherent releases.
3. DATA query/graph/change contracts.
4. PROJ notation/view/artifact contracts and generators.
5. PROJ portal/export integration.
6. Cross-family qualification, historical replay and both-platform evidence.

Do not implement a later layer by bypassing an unimplemented earlier contract.

## Current versus target state

Current executable state is described in [qualification.md](qualification.md). In particular:
- the current lock uses a materialized explicit-version PyArrow DataFusion adapter;
- native Delta/DataFusion FFI is not qualified under the current versions;
- the current repository still uses ty;
- D-032 selects Pyrefly as the target type checker, but the dependency/config migration is separate.

## Non-goals

Do not build an enterprise architecture GUI, graph database, event-sourced micro-edit platform,
custom graph-layout engine, public rendering service, browser editor as a second source of truth,
or overlapping ORM/dataframe/database stack unless a later accepted decision changes scope.

SQLite or immutable Parquet + manifests remain deliberate simplification alternatives to the
selected Delta path; substituting either is an architecture decision, not an incidental refactor.
