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

## Decisions taken during execution

**Eleven tables: six independent collections and five details.** `Element.detail` is normalized
out of `elements` into one table per element-attachable family. data.md warns against a table per
concept, and the line drawn is `ARCH-TOOL-DATA-001` §2C's: a family exists where its information
has type-specific fields, which is precisely why W1 modelled five of them. Keeping detail in the
element row would have meant either a nullable struct per family — five mostly-null columns — or a
union, and DATA-10 forbids the union. The routing is structural rather than conventional:
`compile_tables` dispatches with `match` and `assert_never`, so a sixth element-attachable family
fails `pyrefly check` until the storage layer is told about it.

**Detail tables carry no `model_id`.** They are in exact bijection with one model's detail records
and the element table already holds the scope. A second copy of the same fact is a second thing
that can disagree, and `assemble_model` checks the join it actually performs.

**int64 for every integer.** One integer width across all eleven schemas, including ordinals that
will never exceed a hundred. A mixed-width schema forces a literal cast into every W5 query recipe
and the space saved is irrelevant at the scale data.md commits to. Reversible in W3 and a DATA-56
migration afterwards.

**The baseline persists no nullable struct.** Measured, not assumed: DataFusion 54 returns a
non-nullable child's default — `''` for a string — instead of NULL when the parent struct is null
and the child was built by `Table.from_pylist`; a nullable child reads back correctly, and
`StructArray.from_arrays(..., mask=)` produces a real null that DataFusion reports as NULL.
`to_pylist` says `None` in every case, so the divergence is invisible from Python and appears only
in SQL. The rule that cannot go wrong is to persist no nullable struct at all, with the
conditional rule — every child of a nullable struct is nullable — asserted alongside it and
deliberately vacuous, so it starts biting the moment somebody adds one. Both constructions are
recorded in the matrix.

**List item fields are named `element` in the declaration.** Delta renames them on read, so a
schema calling one `item` would stop matching itself after a single round trip.

**`ReferenceTarget` is flattened into a struct with a discriminator and nullable slots.** Arrow has
a union type and DATA-10 forbids it: a union changes the physical layout when a variant is added.
The discriminator plus nullable slots says the same thing in a layout every engine in the stack
reads identically, and `extra="forbid"` on the domain variants is what rejects a row filling a
slot its variant does not permit.

**A table's digest is defined as the domain digest of the records it encodes.** Not as a hash of
canonicalized bytes. Chunk independence, dictionary independence and metadata independence are
then consequences of the definition rather than properties somebody has to remember to preserve,
and there is one hash implementation, so W4's per-table manifest digest cannot disagree with the
model digest W2 computes. `canonical_table` is the separate *physical* normal form for byte-level
equality assertions and is deliberately not a digest input.

The eleven digests are not a decomposition of the model digest and should not be read as one: the
`elements` digest covers elements without detail, because that is what the table holds. That is
the useful behaviour — it answers *which tables must be republished*, which is what DATA-21's
reuse gate needs — while `model_digest` answers *is this the same model*. W4 records both.

**`pyarrow-stubs` is adopted and qualified rather than trusted.** W1 rejected it for targeting
pyarrow major 20 against the pinned 25. Adopting it takes strict `src` coverage to 100.00% with
zero checker errors, and the qualification is two files because a stub fails in two directions:
`tests/static/pyarrow_surface.py` asserts the types every storage call must have, and
`tests/qualification/test_pyarrow_stub.py` asserts the runtime truth and that every name the stub
declares still exists. Three divergences were found — `Table.equals` declared as returning a
`Table`, a missing `dictionary_decode`, and `pa.schema()`'s capsule overload — and each is pinned
*as declared*, so a corrected stub fails the build and the workaround is removed on purpose.
`docs/toolchain.md` carries the outcome and the `typings/pyarrow/` fallback that was not needed.

**`extensions` landed before any release existed, so no migration was owed.** Adding it to
`Element` and `Relationship` changes what the semantic preimage covers and moved the example's
known-vector digest once. Nothing had been published; the first release is what makes a digest
durable, and `tests/unit/test_semantics.py` now records which of the two reasons a digest may
move.

## Work items

1. **Explicit table schemas** (DATA-10, DATA-11, DATA-12). *Landed.* `storage/schemas.py` declares
   all eleven field by field. `tests/unit/test_storage_schemas.py` asserts what makes them a
   contract rather than a snapshot: baseline types only at any depth, no nullable struct, non-null
   lists and list items, a role on every column, `content_hash` last, and `interface_details` —
   data.md §3A's worked example — pinned literally.
2. **Type conventions** (DATA-12). *Landed.* Five scalar types, `int64` for every integer,
   `timestamp[us, UTC]` and `date32`, no union, extension, dictionary or `large_*` type anywhere.
   The intersection is tested rather than assumed: every convention has a matrix row.
3. **Bidirectional mappings** (DATA-14). *Landed.* `storage/mappings.py` writes each row field by
   field and reads it back through `TypeAdapter.validate_json`, never `model_dump`. Each table is
   exercised with one record whose every Optional is null and every collection empty, and one with
   all of them populated; `compile_tables`/`assemble_model` round-trip the whole model, as a
   property over generated models as well as on the example.
4. **Namespaced extension field** (DATA-13). *Landed* at W3 commit 2 — see
   [the W2/W3 handoff](w2-w3-handoff.md) for why it landed with the domain rather than with
   storage. Sixteen entries, a two-segment namespace, unique `(namespace, key)`, and an AST scan
   that no query, projection or rule reads one.
5. **Arrow metadata policy** (DATA-44). *Landed.* `storage/metadata.py` is the only module that
   touches `.metadata`, proven by a scan that first proves it catches a known-bad read. The
   behavioural half is stronger than the structural one: a table stripped of every key produces
   identical records and identical digests.
6. **Chunk-independent hashing** (DATA-45). *Landed.* `storage/digests.py`, defined over records
   rather than bytes, so the independence is a consequence rather than a property to maintain.
   The gate is asserted both as a fixed example and as a property over drawn batch boundaries,
   with a rename as the negative control.
7. **RecordBatch interchange** (DATA-43). *Landed.* `storage/interchange.py` normalizes arro3
   schemas and readers, pyarrow tables, batches and readers, and anything else exporting the C
   data interface. The materialized path is retained and is what `open()` feeds.
8. **SnapshotProvider Protocol** (DATA-34). *Landed.* Three methods, typed against
   `domain/capsules.py` so the domain still imports no Arrow library. The obligations that are
   behavioural — typed empties, nested nullability, batch-independent rows, `native_ffi_enabled`
   false — are tests, because a signature cannot state them.
9. **MaterializedPyArrowSnapshotProvider** (DATA-34). *Landed.* `register_snapshot` keeps its
   signature and its qualification and delegates to it; `tests/qualification/test_data_stack.py`
   passes untouched, which is the evidence that the behaviour did not change.
10. **arro3 boundary normalization** (DATA-34). *Landed.* Asserted against real arro3 objects
    obtained from a Delta table under `tmp_path`, including that a consumed reader is reported as
    `ConsumedStreamError` rather than as an opaque `OSError`.
11. **Seed the compatibility matrix** (DATA-60). *Landed.* `tests/qualification/test_arrow_matrix.py`
    covers six of §11I's seven dimensions; historical reproducibility needs several published
    releases and is W4's. Two rows are recorded as findings rather than guarantees — DataFusion's
    null-struct child extraction and Delta's loss of schema-level metadata — so an upgrade that
    changes either is visible.

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
