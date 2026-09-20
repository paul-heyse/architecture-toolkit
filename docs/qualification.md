# Qualification scope

## Initial evidence

The qualification suite exercises the locked CPython 3.14 stack with a nested interface
record, nullable scalar, empty collection/table, explicit Arrow types, Delta version history,
materialized pinned-snapshot registration, scalar SQL binding and parallel graph relationships.
Unit tests cover minimal source identity and endpoint invariants. The vendor script independently
checks an ArchiMate SVG, Structurizr DSL validation/export and BPMN XML against local OMG schemas.
These are deliberately limited scaffold checks, not a full release or projection certification.

## Known interoperability limitation

On 2026-09-20, deltalake 1.6.4 rejected native registration with DataFusion 54.0.0 because its
FFI provider requires DataFusion 55.x. The configured package index offered only DataFusion
54.0.0. An API being present did not imply compatible binary interfaces.

The scaffold therefore uses `storage/datafusion_adapter.py`, materializing a specifically
selected Delta version into PyArrow record batches. It also preserves empty-table schema.
Native FFI is disabled and is not counted as a passing test. Upgrade and qualify both libraries
together before changing that decision. Large/unbounded table scans need a separate adapter.

## Still to prove during implementation

- Full normalized metamodel, profile registry and all type/foreign-key/status constraints.
- Multi-table release publication, locking, expected-parent and failure injection.
- Historical schema migrations, retained releases, semantic diff and scenario isolation.
- All generated notation views and agreement on source identities.
- BPMN browser rendering; ArchiMate semantic conformance beyond renderer acceptance.
- Deterministic output across fonts/layout engines and OS versions.
- Real-world model accuracy, evidence review and consumer acceptance.

CI qualifies the locked foundation on hosted macOS ARM64 and Linux x86-64 runners. This does
not imply a test on any particular consumer desktop. The repository's Actions page and the
commit's check results provide the current evidence; do not treat this text as a permanent pass.
