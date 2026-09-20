# Wave 1 — Core domain records, diagnostics and generated schemas

> Milestone: M1 · Requirements: CORE-01..CORE-13, CORE-45; DATA-03..DATA-09, DATA-29..DATA-31,
> DATA-41 · Depends on: W0

## Purpose

Establish what an architecture model *is*. This wave replaces the seven-field placeholder in
`domain/model.py` with the real typed core: semantic scalar aliases, a controlled kind registry, a
relationship registry that knows permitted endpoints and canonical direction, typed detail records,
references and evidence links, the five independent status dimensions, the common `Diagnostic`, the
separate cross-record validation layer, and generated JSON Schema contracts. Command-driven
mutation replaces in-place edits. Nothing is persisted yet.

## Contract references

- [core.md § Pydantic domain](../contracts/core.md) — CORE-01..CORE-13, including the mutation
  pipeline and the bypass prohibition.
- [core.md § Diagnostics and cross-record validation](../contracts/core.md) — CORE-07, CORE-11.
- [core.md § Hypothesis](../contracts/core.md) — CORE-45.
- [data.md § Relational model](../contracts/data.md) — DATA-03..DATA-09.
- [data.md § History and semantic diff](../contracts/data.md) — DATA-29, DATA-31.
- [data.md § Cross-library qualification](../contracts/data.md) — DATA-41.
- Records `ARCH-TOOL-CORE-001` and `ARCH-TOOL-DATA-001`.

## Work items

1. **Semantic scalar aliases** (CORE-03). `domain/identifiers.py` with centralized constrained
   `Annotated` types: `ModelId`, `ElementId`, `RelationshipId`, `ReferenceId`, `ReleaseId`,
   `ChangeSetId`, `ViewId`, `ArtifactId`, `Digest`, `SchemaVersion`, `ProfileVersion`,
   `QualifiedKind`. Constraints live here once and flow into JSON Schema. No repeated raw-string
   rules.
2. **Strict base configuration** (CORE-02, CORE-08). Keep `StrictRecord` with
   `ConfigDict(strict=True, extra="forbid")`; add a frozen `CompiledRecord` base using immutable
   nested types. Pydantic's `frozen` is not deep immutability — choose immutable field types.
3. **Kind and relationship registries** (DATA-04, DATA-05, DATA-06). Replace the seven-member `Kind`
   enum with a controlled registry keyed by qualified kind. The relationship registry declares, per
   type: permitted source kinds, permitted target kinds, canonical direction, inverse display
   label, cardinality and traversal meaning. `Relationship.relationship_type_id` is an unconstrained
   string today. Store one canonical direction and derive inverse views; never persist duplicate
   inverses. `profiles/default/README.md` reserves this work.
4. **Elements and relationships** (DATA-03, DATA-04, DATA-05). `elements` carries `element_id`,
   `model_id`, `kind_id`, `name`, `description`, `lifecycle_state`, `content_hash`. Relationships
   carry their own stable `relationship_id` plus `context_id`, because evidence and decisions attach
   to the relationship itself. Stable identity is independent of display name; aliases may coexist.
5. **Typed detail records** (CORE-04, DATA-07, DATA-30). A field-discriminated `ElementDetail` union
   covering interface, deployment, information-schema, requirement and behavior details. Add a
   detail family only where it has real type-specific fields. Behavior, UML ordering and ERD
   keys/cardinality are modelled explicitly — never inferred from generic edges, because W7b cannot
   generate BPMN gateways or ERD foreign keys from a `supports` edge.
6. **Multi-party interactions** (DATA-08). First-class `interaction`/`handoff` elements with typed
   participant relationships, answering both "which applications participate in this handoff" and
   "which handoffs move this object between roles".
7. **References and evidence links** (DATA-09). `references` and `reference_links` with
   `subject_kind` in element/relationship/field/release, optional `field_path`, and `link_role` in
   supports/contradicts/justifies/qualifies. This stores links; it is not a second evidence
   platform.
8. **Status dimensions** (DATA-29). Promote the five `str` fields to controlled vocabularies:
   design disposition, implementation state, technical qualification, client acceptance,
   evidence/review state. Five independent dimensions, never one linear progression.
9. **Unknown and gap states** (DATA-41). Every dimension and every optional semantic field can
   express unknown, not-applicable, withheld or evidence-gap explicitly. Missing owner information
   is not an invalid foreign key; a manual process needs no application. Never invent a value to
   satisfy a structural rule.
10. **Semantic and layout digest separation** (DATA-31). Distinct `SemanticDigest` and
    `LayoutDigest` aliases, plus the `Diagnostic` category enum encoding the four meanings of
    validation success — structural, cross-model semantic, notation/schema, and real-world
    correctness. Single-sourced here so PROJ-04 and PROJ-07 consume rather than redefine it.
11. **Common Diagnostic** (CORE-07, CORE-11). `validation/diagnostics.py` with the full shape from
    core.md: `diagnostic_id`, `code`, `severity`, `category`, `message`, optional
    `canonical_object_id`, `relationship_id`, `field_path`, `source_location`, `notation_object_id`,
    `rule_id`, `context`, `remediation`. **`source_location` must be present and nullable now**,
    even though W2 populates it — otherwise every diagnostic emitted by W3 and W4 is replumbed
    later.
    Normalize raw Pydantic `ValidationError`s into stable codes such as
    `CORE.DOMAIN.INVALID_ID`.
12. **Cross-record validators** (CORE-06, CORE-07). Record-local rules stay in Pydantic validators
    with an explicit `ValidationContext` (schema version, profile version, mode, flags; no I/O).
    Everything else moves to `validation/` as functions over the candidate returning Diagnostics
    without mutating. Rule families: ID uniqueness and resolution, endpoint kind/direction/
    cardinality, containment and acyclicity, reference and evidence links, schema/interface
    consistency, view membership. Separate hard structural errors from evidence gaps and profile
    expectations.
13. **Change commands** (CORE-04, CORE-09, CORE-10). A discriminated `ChangeCommand` union —
    `AddElement`, `UpdateElement`, `RenameElement`, `RetireElement`, `AddRelationship`,
    `RemoveRelationship`, `UpdateDetail` — with expected base identity where relevant. Candidate
    construction runs baseline plus commands through full Pydantic validation and then cross-record
    validation. A guard test asserts normal flows use no `model_construct()`, `SkipValidation` or
    `model_copy(update=...)`. `tests/unit/test_model.py` currently uses `model_copy(update=...)` to
    test rename and must move to `RenameElement`.
14. **TypeAdapter boundaries** (CORE-05). Use `TypeAdapter` for command batches and registry
    entries. Do not create wrapper models solely to call validation.
15. **Generated JSON Schema** (CORE-12, CORE-13). Versioned schemas for the authoring model, detail
    variants, `ChangeCommand`, profile/config and manifests, with descriptions, discriminator
    mappings and examples. Extend `scripts/check_schema.py` to cover all of them, not just
    `schemas/model.schema.json`. Validation and serialization modes differ only deliberately, and
    the difference is documented.
16. **Hypothesis strategy package** (CORE-45). `tests/strategies/` with `ids.py`, `domain.py`,
    `relations.py`, `commands.py`. Construct valid data directly rather than filtering; cap
    recursion; keep shrinking useful; provide invalid-by-one-rule strategies for validator tests.
    Built here, with the models, so W2 and W5 do not write throwaway strategies.
17. **Refresh the synthetic example.** `examples/minimal/model.yaml` grows to a slice with a
    process, requirement, application, component, interface, data schema and references.
    `test_parallel_relations_and_manual_process_are_preserved` asserts a hard-coded count of 7 and
    will need updating.

## Hard gate

> rename preserves identity
> — [agent handoff](../agent-handoff.md), M1 hard gates

A `RenameElement` command changes the display name and nothing else: `element_id` is unchanged, the
semantic digest changes, and the result is a rename rather than a retire plus an add.

Also required, though not the single gate: **no normal validation bypass APIs** (CORE-09).

## Policy only

CORE-09 — a guard test over the source tree, not a feature.

## Executable checks

```sh
uv run pytest -m "unit or property"
uv run python scripts/check_schema.py
uv run architecture validate examples/minimal/model.yaml
uv run pyrefly check
```

## Evidence

Requirement markers on every test. CORE-12 additionally produces checked-in schema snapshots; CI
fails on drift. A schema snapshot is not evidence that runtime semantics are correct.

## Risks and open questions

- **Registry location.** The relationship registry is generic toolkit content, but permitted
  endpoint matrices are profile-shaped. Decide whether the baseline registry ships in `domain/` with
  `profiles/` overriding, or lives entirely in `profiles/default/`. This affects DATA-05 acceptance.
- **Detail-family scope.** data.md warns against a table per concept. Confirm the five families
  above are the right initial cut before W3 freezes Arrow schemas for them.
- **Vocabulary values** for the five status dimensions are project policy. The current defaults
  (`proposed`, `not_implemented`, `not_qualified`, `not_requested`, `unreviewed`) are placeholders
  and need owner confirmation before W4 makes them durable.
