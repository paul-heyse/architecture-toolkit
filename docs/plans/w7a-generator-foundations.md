# Wave 7a — Generator foundations: Jinja, lxml and the projection artifact model

> Milestone: M4 · Requirements: CORE-32..CORE-44; PROJ-01..PROJ-07 · Depends on: W5

## Purpose

Build the machinery every notation generator uses, and the provenance model that keeps generated
files from becoming a second source of truth. Nothing notation-specific is generated here: this
wave delivers the deterministic Jinja environment, the secure lxml layer with its checksummed local
schema resolver, the C14N digest scheme, and the six artifact concepts — `NotationBinding`,
`ViewDefinition`, `LayoutProfile`, `LayoutArtifact`, `ProjectionArtifact`, `RenderArtifact`,
`ValidationArtifact`.

Splitting this from W7b is deliberate. CORE-38 forbids generating standards XML with Jinja;
CORE-40 and CORE-41 gate the XSD validation that PROJ-19 and PROJ-29 depend on; CORE-43 is what
makes PROJ-27's semantic-versus-DI distinction checkable. These are boundaries that must exist
before the first generator, not constraints applied to one afterwards.

It depends on W5 rather than W6: resolving view membership needs the release-scoped query context,
not the change narrative.

## Contract references

- [core.md § Jinja2 text generation](../contracts/core.md) — CORE-32..CORE-38.
- [core.md § lxml standards XML](../contracts/core.md) — CORE-39..CORE-44.
- [projections.md § Common projection model](../contracts/projections.md) — PROJ-01..PROJ-07 and
  the seven artifact field lists.
- [data.md § Projection metadata bridge](../contracts/data.md) — the relational shapes these
  artifacts compile into.
- Records `ARCH-TOOL-CORE-001` §10–11, `ARCH-TOOL-PROJ-001` §2.

## Work items

1. **Central Jinja environment** (CORE-33). One factory: `StrictUndefined`, controlled package or
   filesystem template root, explicit `trim_blocks` and `lstrip_blocks`, `newline_sequence="\n"`,
   explicit trailing-newline and autoescape policy. No ambient time, random, environment, network
   or filesystem access. `jinja2` is already a declared dependency with no consumer — this is its
   first one.
2. **Typed projection DTOs** (CORE-32). The renderer context is a fully prepared Pydantic DTO built
   by a Python projection builder. Templates may iterate, branch on prepared presentation flags,
   call pure formatting helpers and invoke macros. Templates may not traverse NetworkX, query
   DataFusion, infer relationships, select semantic view membership or fetch evidence.
3. **Template contract check** (CORE-34). At build and qualification time parse each template, run
   `meta.find_undeclared_variables`, compare against the allowed context and globals, and fail on
   an unexpected dependency. `StrictUndefined` remains the runtime defense.
4. **Pure filters** (CORE-35). Deterministic presentation helpers only — identifier escaping,
   notation quoting, label wrapping, sorted deterministic ordering. Business semantics stay in
   Python.
5. **Template bundle identity** (CORE-36). Record the top-level template path and version, the
   transitive included and inherited dependency paths, a digest of the bundle and the
   formatting-filter version. `ProjectionArtifact` references this identity, so a macro change is
   visible as a generator change.
6. **Trusted templates only** (CORE-37). Baseline templates are checked-in toolkit code. No
   arbitrary consumer override without a separately designed sandbox and resource model.
7. **No XML from Jinja** (CORE-38). A guard test asserts no template emits BPMN or ArchiMate
   Exchange XML, and that no XML generator imports the Jinja environment.
8. **Structured XML generation** (CORE-39). `QName`, `ElementMaker` and a central namespace
   registry. Never string-concatenated standards XML.
9. **Secure parser factory** (CORE-40). One factory with no network, no DTD loading, external
   entities disabled, no huge-tree override and no recovery for canonical validation, or the exact
   pinned-lxml equivalent. `scripts/qualify_tools.py` already uses
   `etree.XMLParser(resolve_entities=False, no_network=True)`; generalize that into the shared
   factory rather than repeating it. The `secure-xml-parser` ast-grep rule already fails the
   unsafe keyword forms.
10. **Checksummed local resolver** (CORE-41). Standards schema imports and includes resolve only
    from reviewed local paths recorded in `tools.lock.json`. Unexpected external URI resolution
    fails. The BPMN 2.0.2 XSD set is already pinned; ArchiMate Exchange XSDs are not yet and are a
    W7b prerequisite.
11. **Schema diagnostics** (CORE-42). A `SchemaValidator` adapter loads the pinned schema set,
    parses securely, validates, captures the lxml error log and normalizes findings into the W1
    `Diagnostic` and a `ValidationArtifact`.
12. **Versioned XPath assertions** (CORE-42). Keep identified, versioned XPath checks close to each
    projection's qualification contract rather than scattering string literals through tests.
13. **Digest scheme** (CORE-43). Store both a literal serialization digest and a C14N digest for
    XML artifacts. For BPMN specifically: a semantic C14N digest before DI, and a combined
    semantic-plus-DI digest after layout. C14N normalizes serialization, not architecture
    semantics — canonical identity stays with the model and mapping version.
14. **Defer Schematron and XSLT** (CORE-44). Not baseline; add only with a concrete standards case
    that beats Python validation.
15. **NotationBinding** (PROJ-02). Maps canonical identity to notation identity, keeping display
    name separate from identity, supporting stable renames and letting one canonical object appear
    in several notations without duplicating semantics. Never use SVG-generated IDs, display labels
    or renderer coordinates as canonical identifiers.
16. **ViewDefinition** (PROJ-03). Owns view type, scope, audience, title, description, membership
    policy, included element and relationship IDs, perspective, filter, layout profile,
    publication state and content hash. Semantic membership participates in semantic diff;
    geometry does not. Membership resolution uses the W5 query context.
17. **LayoutProfile and LayoutArtifact** (PROJ-04). Versioned separately from semantic view
    content. A layout artifact is tied to the exact semantic view digest it lays out.
18. **ProjectionArtifact and RenderArtifact** (PROJ-05, PROJ-06). Projection records release, view,
    notation and version, generator and mapping-profile versions, semantic input digest, generated
    source locator and digest, and warnings. Render records renderer, layout engine, platform, font
    profile, options digest, output format, locator, digest and warnings. Renderer bytes never
    enter the semantic hash.
19. **ValidationArtifact and the six dimensions** (PROJ-07). Validation type, validator, validator
    version, ruleset version, result, counts and findings, distinguishing canonical structure,
    cross-model semantics, notation semantics, schema and syntax, renderer import and render, and
    human real-world correctness.
20. **Arrow and manifest integration** (PROJ-01). Compile the artifact families into the typed
    tables data.md §12 specifies, so projection provenance participates in releases and queries.
    The W4 manifest already reserved the digest fields.

## What W6 left for this wave

**A canonical `ViewDefinition` on `Model` breaks seven tables at once.** `projections.md` calls
view membership "semantic governed content", so `ViewDefinition` is the one artifact that may
belong on `Model` rather than beside it. If it lands there, it breaks — in one commit —
`CHANGE_CLASSIFICATION` and `COLLECTION_ORDER` (both asserted total by reflection over `Model`),
`PRESENCE_RULES` and `OPTIONAL_RECORD_RULES`, the `MODEL_COLLECTIONS` literal, `TABLE_IDS` and
`MAPPINGS` — and it needs the first entry in `releases/migration.py::MIGRATIONS`, which is empty
and says so. That is the design working rather than failing, but it is better found here than in a
failing suite.

The layout artifacts are the opposite case. `LayoutProfile`, `LayoutArtifact` and
`ProjectionArtifact` are pinned by digest from the manifest, not reachable from `Model`, so they do
*not* break those tables — and `ChangeNature.STYLE_THEME_ONLY` stays unreachable unless this wave
decides to classify one of their fields. `tests/unit/test_change_classification.py` asserts that
reservation in both directions, so the decision gets asked either way.

**Four reservations this wave clears**: `CORE.VIEW.UNRESOLVED_MEMBER` in `validation/codes.py`,
`DEFERRALS[VIEWS]` in `validation/rules/__init__.py` (which changes the claim-report text every
consumer sees), the note in `validation/rules/profile.py`, and `ProjectionGenerator` in
`domain/protocols.py` — whose signature CORE-58 asks this wave to fill.

**`build` is this wave's verb.** It is the only CLI command left with an untyped stub;
`changes/operations.py::PendingOutput` is the typed shape W6 settled on and W8 expects.

## Hard gate

> Templates do not traverse NetworkX/DataFusion, infer relationships, select semantic view
> membership or fetch evidence.
> — [core contract](../contracts/core.md), Jinja2 text generation

Enforced by the CORE-34 undeclared-variable analysis plus a guard test that no template module
imports `queries` or `storage`.

Also required: a layout-only change produces no semantic diff (PROJ-04), and one canonical object
maps consistently into ArchiMate, C4 and BPMN identities (PROJ-02).

## Policy only

CORE-37, CORE-38, CORE-44 — documented boundaries with guard tests. CORE-61's literal 100% strict
public-API coverage target, deferred from W0, switches on in this wave now that the interfaces have
stabilized.

## Executable checks

```sh
uv run pytest -m "unit or interop"
uv run pyrefly check
uv run pyrefly coverage check
```

## Evidence

Requirement markers throughout. Two properties carry most of the weight: template render
determinism for a fixed DTO and bundle (CORE-33, CORE-36), and C14N digest stability across
formatting-only differences (CORE-43).

## Risks and open questions

- **ArchiMate Exchange XSDs are not pinned.** Adding them to `tools.lock.json` and
  `scripts/bootstrap_tools.py` is a prerequisite for W7b and should land here. Their licence terms
  must be checked before any schema text is vendored.
- **C14N version.** lxml supports C14N 1.0 and 2.0 with different behavior. Pin the choice and
  record it in the artifact, since digests become durable at W8.
- **View membership at scale.** Enumerating membership deterministically is the contract; confirm
  the W5 recipes can express the selections the notation generators actually need.
