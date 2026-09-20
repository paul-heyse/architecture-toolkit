# Wave 7b — Notation generators: ArchiMate, C4, BPMN, UML and ERD

> Milestone: M4 · Requirements: PROJ-08..PROJ-34 · Depends on: W7a

## Purpose

Generate real standards artifacts from canonical releases. Today the repository's only projection
evidence is three handwritten fixtures — `examples/toolchain/architecture.puml`, `workspace.dsl`
and `process.bpmn` — which prove the vendor tools run, not that the toolkit generates anything.
This wave replaces that with generated ArchiMate Exchange XML, generated Structurizr C4, generated
BPMN semantic XML with DI, and schema-derived UML and ERD, each validated and rendered locally.

The largest wave by requirement count, and the one where the admissibility rule bites: a
handwritten fixture that renders is not acceptance evidence.

## Contract references

- [projections.md § C4 / Structurizr](../contracts/projections.md) — PROJ-08..PROJ-16.
- [projections.md § ArchiMate](../contracts/projections.md) — PROJ-17..PROJ-20.
- [projections.md § PlantUML](../contracts/projections.md) — PROJ-21..PROJ-26.
- [projections.md § BPMN](../contracts/projections.md) — PROJ-27..PROJ-34.
- [projections.md § UML and ERD](../contracts/projections.md) — PROJ-23, PROJ-24.
- [toolchain.md § Vendor tools](../toolchain.md) — the pinned JRE, PlantUML MIT build, Structurizr
  WAR and BPMN XSD set.
- Record `ARCH-TOOL-PROJ-001` §4–8.

## Work items

### ArchiMate (PROJ-17..PROJ-20)

1. **Versioned `ArchiMateMappingProfile`** (PROJ-19). Canonical kind to ArchiMate concept, allowed
   conditional mappings, canonical relationship to ArchiMate relationship, required modifiers,
   explicitly unmapped canonical concepts, the relationship validity matrix and a profile version.
   Never infer a mapping from a label.
2. **Relationship validity before export** (PROJ-19). Resolve both mapped concepts, verify the
   ArchiMate relationship type is permitted between them, and check access direction, influence and
   association attributes. An XML-schema-valid document is not sufficient.
3. **Model-level Exchange XML** (PROJ-17, PROJ-18). Via the W7a lxml layer: model identifier, name
   and documentation metadata, elements, relationships, modifiers, property definitions and
   organization groups. Diagram geometry deferred. Exchange XML is an interoperability artifact and
   **never a persistent authoring source** — no automatic import back into canonical state.
4. **Independent import qualification** (PROJ-17). XSD validation, stable IDs, import into Archi
   with no loss of baseline elements, relationships or properties, and an export-import comparison
   on canonical IDs.
5. **PlantUML ArchiMate** (PROJ-20). A separate visual projection from the same view definitions,
   not derived from the Exchange XML.

### C4 and Structurizr (PROJ-08..PROJ-16)

6. **Supported views** (PROJ-08). Baseline system landscape, system context and container.
   Component and dynamic are selective; deployment conditional; code-level diagrams excluded.
7. **Mapping discipline** (PROJ-08). Only software-architecture-relevant concepts map into C4. Do
   not force business capabilities or BPMN gateways into it because the graph contains them.
8. **Deterministic identity** (PROJ-09). Deterministic element and relationship identifiers and
   explicit stable view keys, never display names, with a mapping back to canonical IDs.
9. **Disable inference** (PROJ-10). Emit `!impliedRelationships false` or the supported equivalent.
   Derived relationships appear only through an explicitly derived projection labelled as derived.
10. **Canonical membership** (PROJ-11). The W7a `ViewDefinition` owns membership; the DSL
    enumerates intended objects deterministically. Wildcards are permitted only as tested shorthand
    whose result is compared against canonical membership.
11. **Tags, properties, static perspectives** (PROJ-12). Derived from canonical metadata — kind,
    lifecycle, ownership, qualification, evidence state, scope, classification. External
    URL-driven dynamic perspectives excluded. Structurizr properties are never the only home of a
    semantic fact.
12. **Self-contained DSL** (PROJ-13). No remote includes, mutable workspace extension URLs, scripts
    or plugins, and no Structurizr-hosted narrative docs or ADRs duplicating Notion and Git.
13. **Layout and outputs** (PROJ-14, PROJ-15, PROJ-16). Automatic layout via a versioned
    `LayoutProfile`; any manual layout is a separate `LayoutArtifact` tied to a view digest.
    Structurizr static export is the rich C4 surface and PlantUML or SVG the portable lower-fidelity
    artifact. Filtered views are not baseline. `scripts/qualify_tools.py` already runs
    `validate` and `export`; point them at generated workspaces.

### BPMN (PROJ-27..PROJ-34)

14. **Versioned `BPMNProfile`** (PROJ-28). Explicit supported subset: process and collaboration,
    participants, pools, lanes, common task types, start, end and intermediate events, exclusive,
    parallel and inclusive gateways, subprocesses, sequence, default and conditional flows, message
    flows, boundary events, data objects, stores and associations, text annotations, and groups
    only if the qualified layout pipeline handles them. **Unsupported constructs fail or warn
    explicitly and never silently downgrade to a generic task.**
15. **Semantic XML** (PROJ-27). Generated through the W7a lxml layer with deterministic element
    ordering, explicit conditions and defaults and explicit participant and process references.
    Semantic IDs and DI IDs are separate and both deterministic.
16. **Layered qualification** (PROJ-29, PROJ-30). Canonical validation, then the pinned OMG 2.0.2
    XSD set already in `tools.lock.json`, then bpmn-moddle parse and serialize, then
    `bpmnlint:correctness` as candidate technical diagnostics with recommended rules advisory. The
    ruleset version is recorded.
17. **DI generation** (PROJ-31). bpmn-auto-layout is the preferred candidate, gated on subset
    coverage, deterministic output for the same semantic XML and tool version, collaboration, lanes
    and message flows, data and artifact handling, layout quality, performance and packaging
    footprint. It regenerates DI by design, so semantic and layout versions stay separate and
    hand-edited DI is not preserved.
18. **Local interactive render** (PROJ-32). bpmn-js bundled locally for import and render
    qualification and warning capture, not as an authoring surface. Preserve the required bpmn.io
    watermark and test for it.
19. **Optional static export** (PROJ-33). bpmn-to-image pulls Puppeteer, Chromium and Node >= 24.
    Prefer bpmn-js SVG export through the local harness; keep the heavier path as optional
    milestone-export capability.
20. **Node boundary** (PROJ-34). If Node is adopted: one pinned vendor runtime and one dependency
    lock under the existing `.tools/` bootstrap, bootstrapped and checksummed like the Java tools.
    No second application or workspace, and no persistent service by default.

### PlantUML, UML and ERD (PROJ-21..PROJ-26)

21. **MIT distribution under a restrictive profile** (PROJ-21). The pinned MIT build, not an
    arbitrary main-repository artifact. No remote includes, controlled input and output roots,
    bounded execution time, generated input only.
22. **Stable aliases and optional links** (PROJ-22). Aliases derive from notation bindings; display
    names change without aliases changing. Links and tooltips are presentation only and must be
    qualified for portal mode; portal navigation never depends solely on embedded SVG links.
23. **Selective UML** (PROJ-23). Sequence and state where they add information, class only when it
    materially clarifies implementation. BPMN remains the workflow authority.
24. **Schema-derived ERD** (PROJ-24). Generated from the W3 storage schemas: entity and field IDs
    and names, physical types, primary and unique keys, foreign keys, nullability and cardinality.
    Never infer database cardinality from generic architecture relationships. Validate against the
    schema registry, not by looking at the picture.
25. **Render wrapper** (PROJ-25, PROJ-26). Syntax check and failfast, render, verify the SVG exists
    and parses, capture warnings, version and options into a `RenderArtifact`, and assert expected
    notation bindings appear in the projection source. Argument arrays, never shell interpolation;
    always a timeout. Graphviz is the qualified engine and Smetana a candidate; an engine change is
    a renderer change, and byte-identical SVG across platforms is explicitly not required.
26. **Provenance at first use** (supports PROJ-40, owned by W8). Every vendor invocation writes a
    provenance row. W8's PROJ-40 then becomes a completeness check over rows this wave produced,
    rather than a retrospective archaeology exercise.

## Hard gate

> All notation IDs trace to canonical IDs.
> — [agent handoff](../agent-handoff.md), M4 hard gates

Also required, and the admissibility rule for this wave: *"Vendor handwritten fixtures do not count
as generated-projection acceptance."* Every acceptance artifact must be generated from a canonical
release. The three fixtures in `examples/toolchain/` stay as vendor smoke tests only.

## Policy only

PROJ-13, PROJ-16, PROJ-33, PROJ-34 — documented exclusions and boundaries with guard tests.

## Executable checks

```sh
uv run pytest -m "interop or vendor or qualification"
uv run python scripts/bootstrap_tools.py
uv run python scripts/qualify_tools.py
uv run pyrefly check
```

`qualify_tools.py` grows from three handwritten smoke checks into generated-projection
qualification, and its `canonical_model_projections: "not_implemented"` key becomes real.

## Risks and open questions

- **bpmn-auto-layout is alpha.** If it fails the determinism or subset gates, BPMN DI stays
  unimplemented and PROJ-31 records a strict xfail with the version reason. Do not ship
  nondeterministic layout.
- **Introducing Node is a real scope increase** — a second runtime, lock and bootstrap path. It is
  the gate on PROJ-29, PROJ-31 and PROJ-32. Worth an explicit owner decision before starting.
- **Archi import is a manual qualification step** unless scripted. Decide whether PROJ-17 acceptance
  is a recorded manual procedure or an automated check.
- **ArchiMate Exchange XSD licensing** must be confirmed before vendoring schema text; W7a pins it.
