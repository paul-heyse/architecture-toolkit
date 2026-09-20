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

## Decisions taken during execution

**The hash is versioned in its preimage, and the version is `1`.** `domain/semantics.py`
folds `SEMANTIC_HASH_VERSION` into every digest through a domain-separation prefix, so a later
change to normalization or algorithm is a DATA-56 migration with a new version rather than a
digest that silently disagrees with the manifests W4 will pin. SHA-256 over canonical JSON
(sorted keys, no whitespace, UTF-8, no Unicode normalization) of the validated record; only the
standard library, per `ARCH-TOOL-DATA-001` §8B.

**Collection order is a per-field table, not a global rule.** `COLLECTION_ORDER` names every
tuple-typed field reachable from `Model` and a test asserts the table is total, so a new
collection cannot be hashed until it says whether it is unordered, ordered by its `ordinal`, or
excluded. Ordinal-bearing collections are canonicalized by ordinal: the tuple order in YAML is
presentation and the ordinal is the semantic order, which is what W1 gave behaviour nodes,
transitions, schema fields and participants an ordinal for. `Element.aliases` stays excluded, as
W1 decided. `RelationshipTypeDefinition.ordered_sequence` remains reserved for W5/W6 traversal
and diff semantics.

**The adapter is a subpackage of `domain/`, and parse failures are typed values.**
`domain/authoring/` may import ruamel; nothing else may, and `rules/ruamel-only-in-authoring.yml`
plus an AST scan in `tests/unit/test_layering.py` enforce it. The adapter raises `AuthoringError`
and `validation/normalize.py` turns it into Diagnostics, exactly as it already does for Pydantic
errors, so the authoring layer never imports the validation layer and the dependency order in
`implementation-contract.md` holds. `SourceLocation` moved to `domain/source.py` and
`validation/diagnostics.py` re-exports it, so the class name, the import path and the generated
JSON Schema are unchanged.

**Eleven YAML codes, and a parse failure never enters a claim report.** `CORE.YAML.*` carries
`UNSUPPORTED_VERSION`, `MULTIPLE_DOCUMENTS`, `DEPTH_EXCEEDED`, `ANCHOR`, `ALIAS`, `MERGE_KEY`,
`DUPLICATE_KEY`, `PYTHON_TAG`, `CUSTOM_TAG`, `NOT_A_MAPPING` and `SYNTAX`, each with a fixture
proving its own code, line and column. They are diagnostics, not claims: a document that does not
parse produces no model, so there is nothing for a validation rule to have claimed about it, and
`pipeline.py` reports them on their own before any rule runs. `!!binary`, `!!set`, `!!omap` and
`!!timestamp` are reported as `CUSTOM_TAG` with the tag in `context`; a separate
`UNSUPPORTED_TAG` code for standard-but-non-core tags is an open owner preference.

**Plain data is built from the composed nodes, not from the round-trip loader.** The rt
constructor resolves beyond the YAML 1.2 core schema: `2024-01-01` becomes a `datetime.date`,
`0x1F` a `HexCapsInt`, `!!set` a `CommentedSet`. `build_plain` walks the composed node tree and
converts each scalar by its *resolved tag* against an explicit policy, so a plain `2024-01-01`
stays the string the core schema says it is and the output types are exactly `str`, `int`,
`float`, `bool`, `None`, `tuple` and `dict` — asserted by type identity, which is also CORE-17's
containment guarantee. The same walk produces the SourceMap, so positions and values cannot
disagree.

**The profile guarantees a fixed point, not byte identity for every input.** `dump(load(x))`
equals `dump(load(dump(load(x))))` for every document, preserves comments and quote style, and is
byte-identical for a document already in the profile's own style — `tests/fixtures/authoring/
round_trip/canonical.yaml` proves that. The shipped example's hand-wrapped flow mappings are
re-flowed on the first dump at any width, which is a presentation change and not a semantic one.

**Three ruamel round-trip asymmetries are corrected in the adapter, and all three were found by
the properties rather than by reading the specification.** A plain scalar containing U+0085 is
emitted as a YAML 1.1 line break and folds to a space on reload; a plain scalar beginning with
`?` inside a flow sequence reads back as a complex key; `render.scalar()` double-quotes both. And
ruamel's double-quoted emitter drops the line-continuation backslash on a split it did not make
at a space, so a scalar wrapped just after an escape sequence gains a space that was never
authored — `profile._SafeRoundTripEmitter` withholds that split. The last one is reachable
through `render_model_text` alone at the profile's own width, so it is a defect in what the
adapter writes rather than an artifact of the test strategy. Authored source cannot reach the
matching single-quoted case: ruamel's reader rejects a raw C1 control outright and folds a raw
U+0085 identically on the way in and the way out.

**`record_paths` holds top-level records only.** A participant, a schema field and a behaviour
node each carry an identity key, but a diagnostic addressed at one of those identities means the
record that owns it, so the identity index registers only the six top-level collections and the
semantic grammar reaches everything below.

**Digests are stamped, the model digest is computed.** `stamp_digests` fills every record's
`content_hash` through `model_validate` (nested details first) and is idempotent because
`content_hash` is stripped from every preimage. `Model` carries no digest field: `model_digest`
is computed and W4's manifest records it. The record-level `semantic_delta` (added, removed and
changed identities per collection) is what CORE-20 presents after an edit; classifying those
changes is W6's.

## Work items

1. **Parser factory** (CORE-14). *Landed.* `domain/authoring/profile.py` is the only place a
   `YAML()` is constructed: round-trip mode, YAML 1.2 by default, `preserve_quotes`, explicit
   indentation, width and output settings, an explicit depth bound and duplicate keys as errors.
   A fresh instance per load, because the composer's depth counter was measured not resetting.
   The emitter is subclassed to withhold one unsafe line split; see the decisions above.
2. **Duplicate keys are hard errors** (CORE-15). *Landed.* Found in the event pre-pass, not by
   construction: neither `parse()` nor `compose()` detects a duplicate and the loader never
   constructs a mapping, so the pre-pass owns it and reports the second key's position.
   `allow_duplicate_keys=False` remains the backstop.
3. **Forbidden constructs** (CORE-16). *Landed.* Eleven codes, one fixture each under
   `tests/fixtures/authoring/forbidden/`, headed with the code, line and column the test asserts.
   Every finding in a document is reported, not only the first: the rest travel in `related`.
4. **Presentation containment** (CORE-17). *Landed.* The ast-grep rule confines `ruamel` imports
   to the subpackage, `tests/unit/test_layering.py` proves the exclusion glob the rule test
   cannot, and the adapter's plain output is checked by type identity against exactly `str`,
   `int`, `float`, `bool`, `None`, `tuple` and `dict`.
5. **SourceMap** (CORE-18). *Landed.* `domain/source.py` carries `SourceLocation` (moved from
   `validation/diagnostics.py`, which re-exports it), `SourceEntry` and a frozen `SourceMap` over
   `MappingProxyType` with the source digest, the parser and profile versions, the semantic index,
   the identity index and `record_paths`. Built in the same walk that produces the plain data.
6. **Source-aware diagnostics** (CORE-19). *Landed.* `validation/locate.py` resolves exact
   identity and field path, then the semantic or Pydantic path, then the nearest present ancestor,
   then the document — and records which of the four it used in the diagnostic's `context`, so a
   fallback is a stated fact rather than a misleading position. The render adds `(nearest: …)`
   whenever the located path is not the requested one.
7. **Round-trip editing** (CORE-20). *Landed.* `domain/authoring/editing.py` composes one
   presentation tree, locates records in the live tree by identity, applies each typed
   `ChangeCommand` in the shape `build_candidate` would, dumps, reparses through the same adapter
   and reports a `semantic_delta`. Comments and quote style survive, including the comment block
   above a removed item. A stale `expected_base_digest` is refused before any edit.
8. **Canonical semantic hash** (CORE-21, DATA-27). *Landed.* `domain/semantics.py`; SHA-256 over
   canonical JSON with the version in the preimage, `content_hash` stripped at every depth,
   `COLLECTION_ORDER` asserted total by reflection, and ordinal-bearing collections canonicalized
   by ordinal rather than by position.
9. **Presentation-invariance property** (CORE-21). *Landed.* Requoting, flow and block style,
   inserted comments, reordered mapping keys, shuffled unordered collections, shuffled
   ordinal-bearing lists and a different indent and width — one digest, and an empty delta. The
   negative control renames a single element and asserts it is the only changed identity; it is
   what found the emitter defect recorded above.
10. **CLI wiring.** *Landed.* `architecture validate` reads through `validate_source_text` and
    renders source-located diagnostics: exit 3 for a document that does not parse, 1 for record or
    hard cross-record errors, 0 otherwise. `cli.py` no longer imports ruamel, and `conftest.py`
    and `scripts/check_schema.py` read through the adapter too, so no code path in the repository
    still uses `YAML(typ="safe")`.

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
