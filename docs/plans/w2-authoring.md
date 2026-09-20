# Wave 2 — YAML authoring, source mapping and semantic identity

> Milestone: M1 · Requirements: CORE-14..CORE-21; DATA-27 · Depends on: W1

## Purpose

Make authoring errors point at the line that caused them, and give the model a stable semantic
identity that presentation cannot disturb. The CLI currently does `YAML(typ="safe").load(...)` and
reports Pydantic's own error text, so a bad endpoint nested four levels deep surfaces without a
file, line or column. This wave adds the configured round-trip adapter, the `SourceMap`, the
diagnostic resolution chain, round-trip editing, and the canonical semantic hash.

## Contract references

- [core.md § YAML authoring](../contracts/core.md) — CORE-14..CORE-21, the `SourceLocation` and
  `SourceMap` shapes, and the forbidden construct list.
- [data.md § History and semantic diff](../contracts/data.md) — DATA-27 canonicalization rules.
- [data.md § Pydantic -> Arrow](../contracts/data.md) — DATA-45, which extends the hash in W3.
- Records `ARCH-TOOL-CORE-001` §5 and `ARCH-TOOL-DATA-001` §6A.

## Why the semantic hash is here

DATA-27 would naturally sit with the change records in W6, but three earlier requirements already
depend on it: CORE-20 requires a semantic diff before publication, CORE-21 defines what the hash
excludes, and DATA-45 requires table-level hashes to ignore Arrow chunk layout. DATA-21 then
requires the W4 manifest to pin a semantic digest per table. Landing the hash in W6 guarantees two
competing implementations. Amendment A2 records this.

The **hash primitive belongs in `domain/`** — it is the canonical normal form of a validated record,
not a release concern. Diff computation and change classification stay in `releases/` at W6. Putting
it in `releases/` would make the authoring layer import the release layer and invert the dependency
order in `implementation-contract.md`.

## Work items

1. **Parser factory** (CORE-14). One configured ruamel.yaml round-trip factory: YAML 1.2, quote and
   style preservation, explicit indentation, width and output settings, explicit maximum depth, no
   unsafe type constructors. All authoring reads go through it.
2. **Duplicate keys are hard errors** (CORE-15). Deterministic diagnostic, not a silent last-wins.
3. **Forbidden constructs** (CORE-16). Anchors, aliases, merge keys, custom application tags and
   unsafe Python tags fail with stable codes. Each construct gets a fixture proving the specific
   code, not a generic parse failure.
4. **Presentation containment** (CORE-17). ruamel `CommentedMap` and `CommentedSeq` stop at the
   authoring boundary; domain and storage receive plain data. A guard test asserts no ruamel type
   crosses into `domain/`, `storage/` or `releases/`.
5. **SourceMap** (CORE-18). Built before Pydantic conversion. `SourceLocation` carries source/file
   ID, document ID, semantic path, line, column and optional end position; `SourceMap` carries the
   source digest, parser/profile version, semantic path to location, and canonical ID plus field
   path to location after ID resolution. The SourceMap is build metadata, never architecture
   semantics.
6. **Source-aware diagnostics** (CORE-19). Resolution order: exact canonical ID and field path;
   then semantic/Pydantic path; then nearest parent record; then document level. Populate the
   `source_location` field W1 reserved. Target rendering:

   ```text
   path/to/model.yaml:87:11
   ERROR CORE.RELATION.UNRESOLVED_ENDPOINT
   elements[4].relationships[2].target_element_id
   "software.system.missing" does not resolve.
   ```

7. **Round-trip editing** (CORE-20). Locate record and field, map through the SourceMap, edit the
   round-trip node, preserve comments and style, serialize, reparse, fully revalidate, then compute
   and present the semantic diff. Text substitution is not the mutation method; typed
   `ChangeCommand`s from W1 drive it.
8. **Canonical semantic hash** (CORE-21, DATA-27). `domain/semantics.py` computing a digest over
   validated normalized records. Excluded: comments, quote style, whitespace, key ordering where
   the domain is unordered, and build timestamps. Preserved: authored order for ordered sequences
   such as interaction steps; canonicalize only semantically unordered collections. Carry an
   explicit `hash_algorithm_version` so any later change is a versioned DATA-56 migration rather
   than a silent digest shift.
9. **Presentation-invariance property** (CORE-21). A Hypothesis property using the W1 strategies:
   reformatting a document — requoting, reindenting, adding comments, reordering unordered keys —
   leaves the semantic digest unchanged.
10. **CLI wiring.** `architecture validate` reports source-located diagnostics instead of raw
    Pydantic text, and keeps the honest scope keys already in its report.

## Hard gate

> nested validation resolves to source location
> — [agent handoff](../agent-handoff.md), M1 hard gates

A cross-record failure on a deeply nested field resolves to the correct file, line and column.

Also required, though not the single gate: **forbidden YAML constructs fail deterministically**
(CORE-16).

## Policy only

CORE-17 — a guard test that presentation objects do not escape the adapter.

## Executable checks

```sh
uv run pytest -m "unit or property"
uv run architecture validate examples/minimal/model.yaml
uv run pyrefly check
```

Add a negative fixture directory so CI proves the failure modes, not only the success path.

## Evidence

Requirement markers throughout. The two properties that matter most are presentation-invariance of
the digest (CORE-21) and source-location resolution for nested cross-record failures (CORE-19).
CORE-56's static Pydantic harness from W0 is extended with any new pattern this wave introduces.

## Risks and open questions

- **ruamel line/column fidelity** for deeply nested sequences is the main technical unknown. If a
  position is unavailable the diagnostic must fall back up the resolution chain and say so, rather
  than report a misleading location.
- **Unordered-collection canonicalization** must be decided per field, not globally. Getting this
  wrong makes a reorder look like a semantic change, or hides a real one. The decision belongs in
  the registry from W1.
- **Hash algorithm choice** and its version key are durable: W4 pins the digest into immutable
  manifests. Changing it later is a migration, so decide before W4.
