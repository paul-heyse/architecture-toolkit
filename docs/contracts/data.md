# Data contract

Normative implementation contract for typed storage, queries, releases and architectural history.
Requirements: **DATA-01..DATA-60**.

## Responsibility split

| Layer | Authority |
| --- | --- |
| Pydantic | Domain/commands/manifests/runtime validation |
| PyArrow | Explicit physical schemas and Arrow interchange |
| deltalake Python | Versioned table persistence/history |
| ArchitectureRelease | Coherent multi-table architecture revision |
| DataFusion Python | Release-scoped relational execution |
| NetworkX | Disposable policy-driven graph analysis |
| Semantic diff | Architectural change history |

The selected stack is justified by typed interchange, coherent versioned snapshots and queryability,
not data volume. SQLite or immutable Parquet + manifests remain explicit simplification alternatives.

## Relational model

Persist a typed relational core, not generic JSON node/edge bags:

- elements with stable `model_id`, `element_id`, kind, name and common lifecycle fields;
- independently identified relationships with `relationship_id`, canonical source/target and
  relationship-type registry;
- reference records and typed reference links;
- typed detail tables only when a concept has real type-specific fields/constraints;
- first-class multi-party interactions/handoffs where a binary edge is insufficient.

Relationship registry defines canonical direction, allowed endpoint kinds, cardinality and traversal
meaning. Derive inverse views; do not persist duplicate inverse relationships.

Nest owned value objects. Normalize objects with independent identity or shared relationships.
Small namespaced extensions are escape hatches; frequently queried meaning graduates to typed fields.

## Pydantic -> Arrow

Mappings are explicit and tested. Do not persist arbitrary `model_dump()` JSON as the physical model.

Use:
- explicit nullability;
- string IDs/controlled vocabulary keys;
- UTC microsecond timestamps for instants;
- structs/lists/maps for owned values;
- normalized tables for shared identities;
- tested common PyArrow/Delta/DataFusion type intersection.

Baseline excludes Arrow union/extension types. Empty typed tables must preserve schema.

Schema/field metadata may describe physical storage (schema/table role/generator hints) but cannot be
hidden semantic authority.

Semantic equality/hashes ignore incidental Arrow chunk layout. Dictionary encoding is optional and
qualification-gated.

## Arrow interchange

Promote:
- `RecordBatch` / `RecordBatchReader`;
- Arrow C Stream where the exact stack supports it cleanly;
- PyArrow Dataset/Scanner for lazy reads;
- Parquet metadata for milestone exports/qualification.

PyArrow compute is acceptable for local physical transforms/canonicalization; DataFusion remains the
general relational/query surface. Do not introduce a second Arrow/Acero query architecture.

## SnapshotProvider

All providers:
- require an explicit table version selected by a release manifest;
- preserve expected Arrow schema, typed empties and nullability;
- never resolve published state via implicit latest;
- report provider/library versions for qualification;
- produce logically equivalent rows independent of batch/chunk boundaries.

Target providers:

| Provider | Contract |
| --- | --- |
| `MaterializedPyArrowSnapshotProvider` | Permanent simple fallback; current qualified baseline |
| `PyArrowDatasetSnapshotProvider` | Preferred candidate after exact-stack qualification |
| `ArrowStreamSnapshotProvider` | RecordBatchReader/C Stream candidate |
| Native Delta/DataFusion provider | Optional optimization only when FFI majors align and tests pass |
| `deltalake.QueryBuilder` | Compatibility option, not a separate default query architecture |

The application remains Python-only; do not create a custom Rust implementation for capability completeness.

## DataFusion

Build one fresh `SessionContext` from one `ArchitectureRelease`. Register only manifest-pinned
versions.

Cross-release comparisons use explicit namespaces/sides such as `base.*` and `candidate.*`;
never mix independently resolved latest state.

Use:
- SQL for stable inspectable recipes;
- DataFrame/expression APIs for programmatic construction;
- bound scalar `param_values` or expressions;
- recursive CTEs selectively for naturally relational hierarchy;
- built-ins before UDF/UDAF/UDWF/UDTF.

Versioned query recipe:

```text
query_recipe_id/version
purpose
input table roles
parameter schema
expected output schema
required release/model context
SQL or expression definition
applicable traversal semantics
qualification cases
```

Qualification may capture logical, optimized logical and physical plans plus EXPLAIN/metrics.
Engine plans are diagnostic evidence, not semantic architecture identity.

## NetworkX bridge

Build NetworkX from the same selected release as DataFusion. Follow the CORE graph contract:
canonical relationship IDs are multiedge keys; traversal is policy-driven, bounded and explainable.

## Delta persistence

Use the Python `deltalake` package.

Baseline/qualified targets:
- explicit version/time-travel reads;
- full overwrite snapshots of changed tables;
- table history for storage forensics;
- `CommitProperties.custom_metadata` for publication/change-set provenance after qualification;
- application transaction markers only for per-table retry/idempotency;
- table/schema enforcement;
- simple row-local constraints only;
- explicit schema migration;
- CDF as storage audit/semantic-diff cross-check;
- `scan()` and `to_pyarrow_dataset()` provider candidates;
- checkpoint/retention/vacuum controls.

Do not treat table-level transaction features as multi-table architecture atomicity.

Not baseline:
- custom Rust application implementation;
- automatic schema merge in ordinary publication;
- partitioning/Z-order/compaction tuning without measured need;
- MERGE/UPDATE/DELETE persistence unless scale/behavior justifies it.

## ArchitectureRelease publication

A Delta table version is not an architecture release.

Immutable manifest pins at least:
- release/model/parent/change-set IDs;
- schema/profile versions;
- exact table URI + Delta version + semantic digest;
- source bundle digest/revision;
- generator/toolkit commit;
- validation/change reports;
- required projection/export digests where release policy governs them.

Protocol:

```text
load expected parent
 -> apply complete typed change set
 -> validate candidate
 -> stage changed table snapshots
 -> read back exact staged versions
 -> validate schema/content/artifacts
 -> publish immutable manifest
 -> atomically move current pointer
```

Use one local writer and a publication lock. Stale expected parent fails. A crash may leave orphan
table versions but never expose a partial release.

Cloud/distributed publication is a separate protocol requiring separate qualification.

## Commit provenance and idempotency

Where qualified, Delta commit metadata may include:

```text
publication_attempt_id
change_set_id
model_id
table_id
expected_parent_release_id
storage_schema_version
profile_version
generator_commit
source_bundle_digest
writer/toolkit_version
```

Application transaction markers can make **individual table writes** retry-aware; they never publish
the architecture release.

## History and semantic diff

Keep separate:
1. source/Git history;
2. Delta storage history;
3. architectural semantic history.

Diff stable IDs and typed field values. Preserve authored order for ordered sequences; canonicalize
only semantically unordered collections.

Change categories include add/retire/rename, relationship change, endpoint change, contract/detail
change, requirement applicability/evidence/qualification change, and view/layout change.

Layout/presentation-only changes do not masquerade as semantic model changes. Delta CDF/history are
supplementary audit inputs, not the change narrative.

Alternatives/scenarios have separate model/scenario identity plus explicit baseline, not sequential
release semantics.

Keep design disposition, implementation state, technical qualification, client acceptance and
evidence/review state separate.

## Retention and milestone archives

Never vacuum a Delta version referenced by a retained release or milestone archive.

Milestone export is self-contained and may include:
- manifest;
- complete Parquet snapshots;
- applicable schemas;
- permitted source snapshots;
- semantic change/validation reports;
- generated outputs and provenance.

Live Delta databases and environments remain host-local, outside sync folders.

## Explicit migrations

Schema changes are versioned migrations with:
- old/new schema/profile versions;
- migration function/process;
- historical replay test;
- compatibility/expected change assertions.

Do not rely on automatic schema merge as normal publication behavior.

## Cross-library qualification

Minimum cases through Pydantic -> PyArrow -> deltalake -> explicit version -> SnapshotProvider ->
DataFusion -> Arrow result:

- string IDs/vocabulary keys;
- booleans/integers;
- nullable scalars;
- UTC microsecond timestamps;
- structs/lists/nested nullable values;
- empty typed tables;
- equivalent values with different Arrow chunking;
- optional dictionary encoding;
- schema/field metadata;
- RecordBatchReader/C Stream;
- schema migration vN -> vN+1.

Track type fidelity, metadata fidelity, logical equivalence, query correctness, historical
reproducibility and materialization/memory behavior.
