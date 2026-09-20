# Wave 1 — Core domain records, diagnostics and generated schemas

> Milestone: M1 · Requirements: CORE-01, CORE-02, CORE-03, CORE-04, CORE-05, CORE-06, CORE-07,
> CORE-08, CORE-09, CORE-10, CORE-11, CORE-12, CORE-13, CORE-45; DATA-03, DATA-04, DATA-05,
> DATA-06, DATA-07, DATA-08, DATA-09, DATA-29, DATA-30, DATA-31, DATA-41 · Depends on: W0

## Purpose

Establish what an architecture model *is*. This wave replaces the seven-field placeholder in
`domain/model.py` with the real typed core: semantic scalar aliases, a controlled kind registry, a
relationship registry that knows permitted endpoints and canonical direction, typed detail records,
references and evidence links, the five independent status dimensions, the common `Diagnostic`, the
separate cross-record validation layer, and generated JSON Schema contracts. Command-driven
mutation replaces in-place edits. Nothing is persisted yet.

The difference the wave makes is best stated by what the old model could not refuse. It could say
an element was a `software.system`. It could not say whether `role-1 --contains--> req-1` was a
legal statement, which direction a relationship was authored in, what its inverse was called, or
whether a cycle of containment was an error.

## Contract references

- [core.md § Pydantic domain](../contracts/core.md) — CORE-01..CORE-13, including the mutation
  pipeline and the bypass prohibition.
- [core.md § Diagnostics and cross-record validation](../contracts/core.md) — CORE-07, CORE-11 and
  the eight rule families.
- [core.md § Hypothesis](../contracts/core.md) — CORE-45.
- [data.md § Relational model](../contracts/data.md) — DATA-03..DATA-09.
- [data.md § History and semantic diff](../contracts/data.md) — DATA-29, DATA-30, DATA-31.
- [projections.md § Common projection model](../contracts/projections.md) — PROJ-07's six
  validation dimensions, which `ValidationClaim` is defined at.
- Records `ARCH-TOOL-CORE-001` §3, §4, §6, §7, §12 and `ARCH-TOOL-DATA-001` §2, §6C, §7, §10F.

## Three decisions taken during execution

**The diagnostic taxonomy is three axes, not one enum.** The contracts carry three
enumerations and they answer three different questions, so collapsing them loses information a
reader of a report needs. `DiagnosticCategory` (nine, `ARCH-TOOL-CORE-001` §6) says who emitted a
finding; `ValidationClaim` (six, PROJ-07) says what correctness is claimed; `Disposition` (four,
core.md line 91) says how to treat it. The single four-value enum this document originally
proposed contradicted core.md's own nine and could not distinguish an evidence gap from a profile
expectation. `DATA31_MEANINGS` maps DATA-31's four meanings onto PROJ-07's six claims and a test
asserts the mapping is a true partition, so defining six is a refinement rather than a divergence.

**The baseline registry ships in `domain/`, and profiles override it.** The reusable core stays
general, but a registry containing no relationship types does not satisfy DATA-05. A profile is a
value and `with_overrides` is a pure function over it, so overriding needs no loader, no profile
schema and no resolution order — none of which this wave scopes.

**The wave models the detail the accepted specification states, not the subset this document
first listed.** Ten kind identifiers, the relationship types that must stay distinct, eight
registry properties per type, six detail families, and the `ReferenceTarget` union. Those were
omissions rather than simplifications.

## Work items

1. **Semantic scalar aliases** (CORE-03). *Landed.* `domain/identifiers.py` centralizes every
   constrained `Annotated` alias, plus DATA-31's separate `SemanticDigest` and `LayoutDigest`.
   Patterns are exported constants because the Hypothesis strategies must restate the rule —
   Hypothesis cannot read a Pydantic constraint — and restating it from the constant is what stops
   the two drifting. Every alias uses `StringConstraints`, never `Field`, and a test pins that:
   measured against the pinned versions, only the first form makes `st.from_type` warn, and the
   warning is the guard.
2. **Strict and frozen bases** (CORE-02, CORE-08). *Landed.* `domain/base.py` declares the four
   model families `ARCH-TOOL-CORE-001` §3A names. Both authoring and compiled records are frozen:
   W2 edits the ruamel presentation tree and reparses, so nothing needs a mutable domain record.
   They differ by collection shape, which is load-bearing under `strict=True` — see the risk on
   JSON versus Python mode below.
3. **Kind and relationship registries** (DATA-04, DATA-05, DATA-06). *Landed.* `domain/registry.py`
   carries the ten kinds and the relationship types, each with all eight declared properties
   including `validation_rule_ids`, which the rule layer now cross-checks. DATA-06 is structural:
   there is one direction field and one inverse label, so a duplicate inverse has nowhere to live.
4. **Elements and relationships** (DATA-03, DATA-04). *Landed.* Seven and eight columns
   respectively, matching `ARCH-TOOL-DATA-001` §2A/§2B. Readable aliases live on the element and
   are excluded from semantic identity.
5. **Typed detail records** (CORE-04, DATA-07, DATA-30). *Landed.* Six families; five attach to an
   element and notation bindings are the sixth, in `domain/notation.py`, because their subject may
   be a relationship. The three BPMN gateway types, transition guards, ERD key membership and
   field ordinals are stated explicitly — W7b cannot derive any of them from a generic edge.
6. **Multi-party interactions** (DATA-08). *Landed.* A first-class `Interaction` with typed
   participants, answering both questions §2D poses.
7. **References and evidence links** (DATA-09). *Landed.* Plus the `ReferenceTarget` union, so a
   link can support an interface's authentication mechanism rather than a whole application.
8. **Status dimensions** (DATA-29). *Landed.* Five independent `StrEnum`s, asserted disjoint from
   each other and from the lifecycle state. The disjointness guard found two real collisions on
   first run and both are fixed.
9. **Unknown and gap states** (DATA-41). *Landed.* A shared `GapState` in the union of every
   dimension, so an unknown is a stated value rather than a missing field. `design_disposition`
   and `implementation_state` default to `unknown` because `proposed` and `not_implemented` would
   assert things nobody said.
10. **Semantic and layout digest separation** (DATA-31). *Landed.* Distinct aliases, and the
    claim axis described above.
11. **Common Diagnostic** (CORE-07, CORE-11). *Landed.* `validation/diagnostics.py`, exactly the
    thirteen fields core.md specifies, with `source_location` present and nullable. Claim and
    disposition are read from the code registry rather than stored, so two occurrences of one code
    cannot disagree.
12. **Cross-record validators** (CORE-06, CORE-07). *Landed.* All eight families declared; seven
    populated and views carrying a recorded deferral to W7a. Thirteen rules, each with a known-bad
    fixture that must trigger it. `ValidationContext` carries §3G's four fields and reaches nested
    validators through `info.context`.
13. **Change commands** (CORE-04, CORE-09, CORE-10). *Landed.* Seven variants plus `ChangeSet`.
    `RenameElement` is deliberately narrower than `UpdateElement`; retyping is unexpressible.
    `no-validation-bypass` now covers `tests/` and `scripts/`, which the old rename test blocked.
14. **TypeAdapter boundaries** (CORE-05). *Landed.* Command batches, registry entries, detail and
    reference fragments, and reusable schema generation — the four §3E names.
15. **Generated JSON Schema** (CORE-12, CORE-13). *Landed.* Seven declared families, five emitted
    and two reserved for W4 and W5, each versioned in `$id`. `scripts/check_schema.py` grew from
    one hardcoded path to six directory-driven jobs. CORE-13 is mechanical: the two schema modes
    must be byte-identical while no computed field exists.
16. **Hypothesis strategy package** (CORE-45). *Landed.* Four of the eight groups core.md names;
    the other four have no models until W4, W5 and W7a and are recorded in `DEFERRED_GROUPS`
    rather than left absent. Values are built directly, never filtered.
17. **Refresh the synthetic example.** *Landed.* Every kind, every relationship type, a handoff,
    an evidence link addressed at one field, a notation binding, and two deliberate gaps.

## Hard gate

> rename preserves identity
> — [agent handoff](../agent-handoff.md), M1 hard gates

A `RenameElement` command changes the display name and nothing else: `element_id` is unchanged, the
element is present before and after rather than retired and re-added, and kind, lifecycle, status,
aliases, detail and every relationship are untouched. Asserted as a Hypothesis property over
generated models, not as a single example.

Also required, though not the single gate: **no normal validation bypass APIs** (CORE-09).

## Policy only

CORE-09 — enforced by the `no-validation-bypass` structural rule, not a feature.

## Executable checks

```sh
uv run pytest -m "unit or property"
uv run python scripts/check_schema.py
uv run architecture validate examples/minimal/model.yaml
uv run architecture schema --write   # regenerate; the drift check compares against this
uv run pyrefly check
```

## Evidence

Requirement markers on every test. CORE-12 additionally produces checked-in schema snapshots and
CI fails on drift. A schema snapshot is not evidence that runtime semantics are correct, which is
why `check_schema.py` also asserts the generated schema and Pydantic agree about the example.

## Risks and open questions

- **Status vocabulary values are provisional.** `EvidenceReview` is the only one with a source.
  They are cheap to change until W4 pins them into immutable manifests and expensive afterwards,
  so they want owner review inside this milestone.
- **The four gap states are a repo invention**, consistent with `ARCH-TOOL-DATA-001` §3B's
  "explicit nullable fields, with a separate status where the reason for missingness matters" but
  not specified there.
- **Six detail families means six typed detail tables at W3.** data.md warns against a table per
  concept; confirm the cut before W3 freezes Arrow schemas, not after.
- **Strict mode treats JSON and Python input differently, and it matters.** A Python `list` handed
  to a `tuple[...]` field fails with the error location collapsed to the field, discarding every
  nested error; the same payload through `model_validate_json` reports the full path. The
  authoring path is therefore JSON until W2 supplies the proper adapter. Pinned by a test.
- **Status vocabularies cannot be extended by a profile**, because they are closed `StrEnum`s. The
  registry is profile-overridable; these are not. Revisit if a consumer profile needs its own.
- **`--public-only` is still unused.** W0 deferred the underscore-prefixed internal-module
  convention to this wave and it has not been adopted; the coverage gate remains whole-module.
