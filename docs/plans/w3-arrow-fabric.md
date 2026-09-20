# Wave 3 — Arrow fabric: explicit physical schemas and interchange

> Milestone: M2 · Requirements: DATA-10..DATA-14, DATA-34, DATA-43..DATA-45 · Depends on: W2

## Purpose

Give the validated domain a physical representation. This wave writes explicit PyArrow schemas for
every compiled table, the tested Pydantic-to-Arrow mappings in both directions, the Arrow metadata
policy, and the chunk-independent table-level hash. It also generalizes the one existing adapter —
`storage/datafusion_adapter.register_snapshot` — into the `SnapshotProvider` boundary that W4 needs,
without changing its behavior.

No Delta writing and no releases yet. The deliverable is: a validated model becomes a set of typed
Arrow tables and comes back unchanged.

## Contract references

- [data.md § Pydantic -> Arrow](../contracts/data.md) — DATA-10..DATA-14, DATA-45.
- [data.md § Arrow interchange](../contracts/data.md) — DATA-43, DATA-44.
- [data.md § SnapshotProvider](../contracts/data.md) — the provider table; DATA-34.
- [data.md § Cross-library qualification](../contracts/data.md) — the minimum type case list.
- [core.md § Typed subsystem interfaces](../contracts/core.md) — the `SnapshotProvider` Protocol
  stub from W0 is filled in here.
- Record `ARCH-TOOL-DATA-001` §3 and §11B–11C.

## Work items

1. **Explicit table schemas** (DATA-10, DATA-11, DATA-12). `storage/schemas.py` with a hand-written
   `pa.schema` per table: elements, relationships, the typed detail families from W1, references
   and reference links. Nest owned values as structs and lists; normalize anything with independent
   identity. The interface-detail schema in data.md §3A is the worked example — a `transport`
   struct owned by the row, with request and response schemas referenced by ID.
2. **Type conventions** (DATA-12). String IDs and controlled-vocabulary keys; explicit nullability
   with a separate status field where the reason for missingness matters; UTC microsecond
   timestamps for instants and dates for day precision. **No Arrow unions and no extension types in
   the persisted baseline.** Target the tested intersection of Arrow, Delta and DataFusion rather
   than assuming every Arrow type round-trips.
3. **Bidirectional mappings** (DATA-14). Explicit, tested mappings between W1's Pydantic models and
   these schemas, in both directions. Do not persist arbitrary `model_dump()` JSON as the physical
   model, and do not start by building a universal converter for arbitrary Python types.
4. **Namespaced extension field** (DATA-13). A small escape hatch for unusual annotations, with a
   documented rule that frequently queried meaning graduates into a typed field rather than
   accumulating.
5. **Arrow metadata policy** (DATA-44). Schema and field metadata may carry storage schema version,
   table semantic role, generator/toolkit version and representation hints. A guard test asserts no
   code path reads domain meaning out of metadata — metadata is self-description, never hidden
   semantic authority.
6. **Chunk-independent hashing** (DATA-45). Extend W2's `domain/semantics.py` to table level.
   Identical logical values with different `RecordBatch` boundaries produce the same digest. Ordered
   domain collections keep their order; unordered ones canonicalize independently of chunking.
   Dictionary encoding stays optional and qualification-gated.
7. **RecordBatch interchange** (DATA-43). Use `RecordBatch` and `RecordBatchReader` as the principal
   physical exchange objects, keeping the materialized path as the retained fallback. Qualify the
   Arrow C Stream boundary where components support it cleanly.
8. **SnapshotProvider Protocol** (DATA-34, and the W0 stub). Fill in the Protocol: require the exact
   version named by a manifest, expose the expected Arrow schema for that version, preserve typed
   empty tables and nested nullability, **never resolve an implicit latest version**, report
   provider type and library versions in diagnostics, and produce logically equivalent records
   regardless of batch boundaries.
9. **MaterializedPyArrowSnapshotProvider** (DATA-34). Wrap the existing `register_snapshot` without
   behavior change. It already rejects a non-integer or negative version and synthesizes an empty
   batch per field so an empty table keeps its schema — both behaviors are contract requirements and
   must be preserved. This provider remains supported permanently, even after lazy providers
   qualify.
10. **arro3 boundary normalization** (DATA-34). deltalake returns Arrow objects through arro3 in
    places, so not every returned object is literally PyArrow. Normalize at one place and test it,
    rather than assuming older examples still apply.
11. **Seed the compatibility matrix** (extends DATA-60, owned by W4). Add the Arrow-only cases from
    data.md now: string IDs, booleans and integers, nullable scalars, UTC microsecond timestamps,
    structs, lists, nested nullable combinations, empty typed tables, differing chunk layouts,
    optional dictionary encoding, schema and field metadata, and RecordBatchReader.

## Hard gate

> Semantic equality/hashes ignore incidental Arrow chunk layout.
> — [data contract](../contracts/data.md), Pydantic -> Arrow

Two Arrow tables holding identical logical values with different batch boundaries hash equal; a
single changed field value does not.

## Policy only

DATA-13 — the extension escape hatch is a documented constraint plus a guard test that it stays
small.

## Executable checks

```sh
uv run pytest -m "unit or integration"
uv run pyrefly check
```

## Evidence

Requirement markers on every case. The compatibility matrix rows seeded here carry DATA-60 markers
so W4 and W9 extend one artifact rather than three.

## Risks and open questions

- **Nested nullability round-tripping** through Delta is the known soft spot; W4 proves it end to
  end, but schema decisions that make it hard are taken here.
- **Dictionary encoding** is tempting for controlled-vocabulary columns and explicitly
  qualification-gated. Leave it off in the baseline.
- **Detail-family churn.** Freezing Arrow schemas for W1's detail families makes later additions a
  DATA-56 migration. Confirm the W1 family cut before this wave lands.
