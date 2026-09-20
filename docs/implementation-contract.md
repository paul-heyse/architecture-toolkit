# Implementation contract

## Target flow

Authored YAML/JSON → strict Pydantic domain objects → explicit Arrow tables → validated
Delta snapshots → immutable release manifest → DataFusion catalog / NetworkX projection →
notation-specific outputs → local documentation bundle.

All stages share stable model, element, relationship and reference identities. Pydantic owns
domain validation; Arrow owns column types; Delta owns individual table history; the release
manifest owns the coherent architecture revision. DataFusion performs relational queries;
NetworkX MultiDiGraph supplies disposable, typed graph traversals. No engine is a second
independent source of architectural truth.

## Package boundaries

| Directory | Responsibility |
| --- | --- |
| `src/architecture_toolkit/domain` | Types, identities, relation registry, profiles, status dimensions |
| `storage` | Explicit Arrow mappings and version-pinned Delta adapters |
| `queries` | Parameterized relational queries and named graph policies |
| `releases` | Manifest, semantic diff, staging, lock and atomic publication |
| `validation` | Structural, cross-record, evidence and notation diagnostics |
| `projections` | ArchiMate, BPMN XML, Structurizr, UML and schema-derived ERD |
| `rendering` | Bounded local vendor subprocesses, artifact provenance |
| `publishing` | Local MkDocs bundle and portable export manifests |
| `profiles` | Versioned consumer extensions, no embedded client model |
| `schemas` | Generated authoring JSON Schema and future explicit storage schemas |
| `examples` | Synthetic source fixture and separate handwritten tool qualification fixtures |
| `tests` | Unit invariants and real dependency qualification |
| `reference` | Generic requirement index and public source catalog |

Only the minimal domain model, CLI and materialized snapshot adapter are implemented.
The remaining package directories are deliberate extension points, not functioning services.

## Required contracts

Persist normalized elements, independently identified typed relationships, references and
reference links. Add typed interface, deployment, schema/field, behavior, requirement and
notation detail tables where constraints justify them. Nest owned values; normalize shared
identities. Represent a multi-party interaction as an object with typed participants.

A relationship registry must constrain direction, endpoint kinds, cardinality and traversal
meaning. Store one canonical direction and derive inverses. Named graph queries declare edge
kinds, direction, context and stopping rules, returning paths, release and policy versions.
Reachability alone must not be reported as certain failure propagation.

Use explicit nullable Arrow types, UTC microsecond instants and tested nested structs/lists.
Keep unknown/not-applicable/withheld distinctions explicit. Namespaced extensions are bounded
escape hatches. SQL values use scalar bindings, never string formatting. Mutation APIs are
separate from read queries. The materialized adapter has memory proportional to the table;
qualify a streaming/native replacement separately before using it on larger models.

A release pins every table version, schema/profile version, source digest, generator commit,
change report and output digest. Use one local writer, a lock, an expected-parent comparison,
staging and readback; expose a completed immutable manifest before atomically replacing the
current pointer. Delta has no implied cross-table transaction. Failed staging may leave orphan
versions, but must never change current to an incomplete release. Cloud/distributed publication
requires a separately qualified protocol.

Diff stable identities and field values, preserving authored sequence order; sort only
semantically unordered collections when hashing. Keep layout changes separate. Preserve
rationale, author and decision references. Alternatives have separate scenario/model identity.
Retain files needed by historical manifests; package milestone exports with Parquet, manifest,
schemas, permitted source snapshots and outputs. Source Git history, Delta history and
architectural change history are separate concepts.

Keep design disposition, implementation, qualification, client acceptance and evidence review
separate. Validation reports must distinguish structure, cross-model semantics, notation and
real-world correctness. Unknown evidence creates visible gaps; broken foreign keys are errors.

## Projection contract

ArchiMate describes architecture concepts; BPMN needs explicitly modeled events, gateways,
participants and ordered flows. C4 views come from generated Structurizr DSL/JSON; selective
UML captures explicitly modeled sequence/state/class semantics. ERD comes from actual storage
schemas with keys/cardinality, not guesses from labels. Maintain source-to-view traceability.
Use Jinja2 for bounded text templates and lxml for namespace-aware BPMN XML. Do not infer
workflow execution semantics from generic graph edges or promise lossless GUI round trips.

Render through local PlantUML/Structurizr and a qualified local BPMN renderer; Kroki is optional.
Do not send models to public render services by default. No paid GUI or server is required.
Generated MkDocs is a local artifact first, not automatic GitHub Pages publication.

## Acceptance index

`reference/requirements.json` contains DATA-01 through DATA-42. Its status describes the full
requirement, so partial scaffold evidence does not mark a requirement completed. Section labels
are locators into the maintainers' narrative specification, not public document links.
Each implementation PR should identify requirements, tests, remaining gaps and design decisions.
SQLite or immutable Parquet plus manifests remain valid simplification alternatives; adopting
one would be an explicit documented design change, not an accidental dependency substitution.
