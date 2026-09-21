# Wave 4 — Delta persistence, SnapshotProviders and coherent releases

> Milestone: M2 · Requirements: DATA-19..DATA-25, DATA-37, DATA-39, DATA-51..DATA-60 ·
> Depends on: W3

## Purpose

Turn typed Arrow tables into versioned storage and coherent, immutable architecture releases. Delta
gives per-table version history; it gives no multi-table atomicity, so the release protocol is an
application protocol layered above it. This is the largest wave and the one where correctness is
hardest: a crash mid-publication may leave orphan table versions but must never expose a partial
release.

## Contract references

- [data.md § Delta persistence](../contracts/data.md) — DATA-51..DATA-60.
- [data.md § ArchitectureRelease publication](../contracts/data.md) — DATA-19..DATA-25 and the
  eight-step protocol.
- [data.md § Commit provenance and idempotency](../contracts/data.md) — DATA-53, DATA-54.
- [data.md § Retention and milestone archives](../contracts/data.md) — DATA-25, DATA-58.
- [data.md § Explicit migrations](../contracts/data.md) — DATA-56.
- [toolchain.md § DataFusion / Delta compatibility](../toolchain.md) — the current FFI limitation.
- Record `ARCH-TOOL-DATA-001` §5 and §11B, §11F–11I.

## Decisions taken during execution

**Retention is a computation over manifests, not a policy number.** Nothing is vacuumed by
default and no release is ever dropped. The protected set is every Delta version every manifest in
the store pins, handed straight to deltalake's `vacuum(keep_versions=...)`. A retention count
would be a number to get wrong, and the volume here does not justify one; milestone archives are
the answer to disk growth, because they are self-contained and do not depend on the live Delta
directory surviving. `probe_readability` is the other half: a release made unreadable by anything
outside `retention.py` is reported rather than discovered at read time.

**All four provider rungs are qualified and the materialized one stays the default.** DATA-52 says
to qualify the Dataset and stream providers *before* replacing the materialized one, and
qualifying is not replacing. Changing a qualified default is a measured decision, not a side
effect of the wave that first tested the alternatives.

**The native FFI provider is a class that always refuses.** deltalake 1.6.4 exports a DataFusion
55.x table provider against a DataFusion 54 lock and the library rejects the mismatch itself, so
the refusal is upstream. It is written as code rather than prose because `docs/agent-handoff.md`
says never to enable it merely because import and registration exist, and a rule expressed as a
class is one somebody has to delete deliberately. Its test fails when the majors align, which is
the moment to enable the rung on purpose.

**deltalake records an application transaction marker and does not act on it.** Replaying the same
`Transaction(app_id, version)` is accepted and produces a second commit. So DATA-54 idempotency is
a read-then-skip that this toolkit implements: `transaction_version` is consulted before every
write. The marker is the library's, the skip is ours, and `releases/staging.py` says so rather
than leaving a reader to assume the library did more than it does.

**An identical overwrite still creates a Delta version**, so DATA-22's "reuse unchanged versions"
means *not writing at all* when the digest matches, and carrying the parent's version into the new
manifest. A one-element rename moves one pin and leaves ten where they were, which makes the reuse
gate a diff of two manifests rather than a claim.

**Every `deltalake` call lives in `storage/delta.py`.** `implementation-contract.md` already gave
`storage` "Delta persistence" and `releases` "manifest, lock/staging/publication";
`rules/releases-no-direct-delta.yml` and a layering test make that structural, so a change of
storage engine is one module rather than a search.

**`schema_mode` is typed `Literal["overwrite"] | None`**, which turns DATA-56's "do not rely on
automatic schema merge" into a type. deltalake also accepts `"merge"`; a caller reaching for it
fails `pyrefly check`.

**`tip()` is the one deliberate `version=None` in the toolkit** — a writer reading back the number
it just committed, under the lock, so the manifest can pin it explicitly. Invariant 5 forbids a
published *release* resolving an implicit latest version, which this is not, and an AST guard
keeps the exception to one call. The guard scans the syntax tree rather than the text, because a
text count matched the three mentions in that function's own docstring.

**The eight steps are individually addressable, and the fault-injection gate is parametrized over
them.** Writing that gate sharpened what "no partial state" claims: a failure at step eight happens
after step seven has written the manifest, so an orphan manifest exists — and that is the
permitted state, because a manifest nothing points at is a file rather than a release. The
invariant is about the pointer, not about what is lying on disk.

**The migration registry is empty, and that is the honest state.** `STORAGE_SCHEMA_VERSION` has
only ever been `1.0.0` and nothing has been published against an earlier one. The machinery is
production code and a synthetic `1.0.0 -> 1.1.0` step exercises it end to end, including the
property that makes retention worth anything: a migration writes new versions and the pinned ones
still read under their old schema.

**One finding fed back into the provider layer.** Under deltalake 1.6.4, `DeltaTable.scan()`
returns string columns as `string_view` where `to_pyarrow_table()` and `to_pyarrow_dataset()`
return `string`. Values are identical and the cast is lossless, but §11B requires a provider to
expose *the expected* schema, so `ArrowStreamSnapshotProvider` casts each batch lazily on the way
out. The divergence is pinned in the matrix with a message naming what to do when upstream agrees,
so the cast cannot outlive its reason.

**Check constraints are applied as a maintenance call, not during publication.** Adding one is a
Delta commit, so doing it inside publication would make the version a manifest pins depend on
whether the table happened to be new. Publication's version arithmetic stays boring.

## Work items

1. **Delta writing** (DATA-22). Write a complete replacement snapshot for each changed table and
   reuse existing versions for unchanged tables. No replay-based event sourcing in which history is
   reconstructed from thousands of micro-edits. MERGE, UPDATE and DELETE stay out of the baseline.
2. **Three histories kept separate** (DATA-19). Source history in Git, storage history in Delta,
   architectural history in semantic change records. Delta supplies versioning, not interpretation.
3. **ArchitectureRelease manifest** (DATA-20, DATA-21). Immutable, pinning release, model, parent
   and change-set IDs; schema and profile versions; per-table URI, exact Delta version and semantic
   digest from W2; source bundle digest; generator/toolkit commit; validation and change reports.
   **A Delta version number is never the architecture release number.** Readers load the manifest
   once and open exactly the versions it names. The `no-implicit-latest-delta-version` ast-grep
   rule already fails any `DeltaTable(...)` opened without an explicit `version=`.
4. **Reserve the projection fields now** (extends DATA-21, filled by W8). Declare
   `projection_artifact_digests`, `render_artifact_digests` and `validation_reports` as optional and
   empty. Adding them at W8 instead would force a DATA-56 migration on every existing release.
5. **Publication protocol** (DATA-23, DATA-24). Load expected parent; apply the typed change set;
   validate the candidate; stage changed table snapshots; read back the exact staged versions;
   validate schema, content and required artifacts; publish the immutable manifest; atomically move
   the current pointer. One local writer plus a publication lock. A stale expected parent fails.
6. **Step-addressable publication API** (supports CORE-46 in W9). Expose the protocol as named,
   individually injectable steps so W9's Hypothesis state machine can drive it without refactoring.
   Designing this in later is expensive.
7. **Fault injection** (DATA-24). Deterministic `monkeypatch` and `tmp_path` failure at every stage
   boundary. After each, assert the current pointer still resolves to the previous complete release
   and no partial state is visible. Orphan staged versions are permitted.
8. **SnapshotProvider qualification ladder** (DATA-51, DATA-52). Keep the materialized provider as
   the default. Qualify, in order and against the actual lock: `to_pyarrow_dataset()` into
   DataFusion `register_dataset`; then `DeltaTable.scan()` / RecordBatchReader / C Stream; then
   `deltalake.QueryBuilder` as a compatibility option for selected recipes. Each must pass the full
   type and release matrix before becoming default.
9. **Native FFI stays disabled** (DATA-52, DATA-60). deltalake 1.6.4 exports a DataFusion 55.x FFI
   provider while the lock pins DataFusion 54; the library rejects the mismatch. Never enable it
   merely because the import and registration exist. Enabling it requires aligned majors and
   both-platform qualification.
10. **Commit provenance** (DATA-53). Where qualified, attach `CommitProperties.custom_metadata`:
    publication attempt ID, change set ID, model ID, table ID, expected parent release ID, storage
    schema version, profile version, generator commit, source bundle digest, writer version.
11. **Per-table idempotency** (DATA-54). Qualify application transaction markers for retry safety
    on a single table. A successful app transaction never means the release is published.
12. **Constraint boundary** (DATA-55). Delta check constraints only for row-local persisted
    invariants. Endpoint validity, cross-table referential rules, graph and cardinality semantics,
    evidence requirements and release coherence stay application validations.
13. **Explicit migrations** (DATA-56). Versioned migrations carrying old and new schema/profile
    versions, the migration process, a historical replay test and expected-change assertions. Never
    `schema_mode="merge"` as ordinary publication behavior.
14. **CDF and history as audit only** (DATA-57). Use Delta history and change data feed for
    debugging, storage forensics and cross-checking the semantic diff. They are not the
    architectural change narrative.
15. **Retention safety** (DATA-25, DATA-58). Vacuum must never invalidate a version referenced by a
    retained manifest, a milestone archive or a supported replay test. Implement retention as a
    manifest-aware operation that refuses unsafe vacuums.
16. **Milestone archives** (DATA-25). Self-contained export: manifest, complete Parquet snapshots,
    applicable schemas, permitted source snapshots, change and validation reports. Ship the writer
    now with an empty `outputs/` section; W8 fills it without a format change.
17. **Proportionate physical design** (DATA-39, DATA-59). No partitioning, Z-ordering, elaborate
    compaction or custom indexes. Rebuild the query catalog from the manifest; DataFusion's default
    catalog is in-memory, which suits this.
18. **Source identity** (DATA-37). Record source revisions and content hashes. Where a source has
    no immutable revision API, preserve an authorized snapshot and digest rather than pretending a
    mutable URL identifies a version.
19. **Own the compatibility matrix** (DATA-60). Extend W3's Arrow-only cases through the full path:
    Pydantic, PyArrow, deltalake write, exact Delta version, SnapshotProvider, release-scoped
    DataFusion, Arrow result. Track type fidelity, metadata fidelity, logical row equivalence,
    query correctness, batch independence, historical reproducibility and materialization behavior.
    Add the vN to vN+1 migration case. W9 proves it on both platforms.
20. **Local storage stays local.** Live Delta directories live under ignored `.runtime/`, never in a
    sync folder.

## Hard gate

> Fault injection after every publication stage never exposes partial state.
> — [agent handoff](../agent-handoff.md), M2 hard gates

Also required: a stale expected parent fails; unchanged table versions are reused; retained
historical releases remain readable.

## Policy only

DATA-20, DATA-55, DATA-59 — boundary statements enforced by guard tests, not features.

## Executable checks

```sh
uv run pytest -m "integration or qualification"
uv run pyrefly check
```

Fault-injection tests are local and deterministic (CORE-51). No network, no sleeps.

## Risks and open questions

- **Read-back cost.** Step five reads back every staged version before publication. Correct, and
  the right default at this scale; revisit only with measurements.
- **Lock discipline.** One local writer is the contract. Cloud or distributed publication is
  explicitly a separate protocol requiring separate qualification — do not generalize the lock
  speculatively.
- **`CommitProperties` and app transactions** (DATA-53, DATA-54) may not be exposed by the pinned
  deltalake in the form the contract assumes. If not, mark strict xfail with the version reason
  (CORE-52) rather than working around it.
- **Retention policy values** — how many historical releases stay readable — are an owner decision
  that affects vacuum safety and archive volume.
