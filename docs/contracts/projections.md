# Projection contract

Normative implementation contract for standards mapping, projection, rendering and publishing.
Requirements: **PROJ-01..PROJ-42**.

## Common projection model

Canonical architecture remains the sole semantic source.

Required concepts:

```text
NotationBinding:
  binding_id
  canonical_object_id
  notation / notation_type / notation_object_id
  optional view_id
  mapping_profile_version
  optional projection_artifact_id / link_target

ViewDefinition:
  view_id / view_type / notation
  scope / audience / title / description
  semantic membership
  perspective / filter
  layout_profile_id
  publication_state
  content_hash

LayoutProfile:
  notation / renderer family / layout engine
  direction / spacing / routing / style / font profile / version

LayoutArtifact:
  view_id / view semantic digest / profile
  geometry or locator / engine/version / digest

ProjectionArtifact:
  release_id / view_id / notation
  generator + mapping-profile versions
  semantic input digest
  generated source locator/digest
  optional layout artifact / warnings

RenderArtifact:
  projection_artifact_id
  renderer/layout engine/version
  platform/font/options
  output format/locator/digest
  warnings

ValidationArtifact:
  release/projection IDs
  validation type / validator / ruleset version
  result / findings
```

View membership is semantic governed content. Coordinates, bendpoints, SVG internals, fonts and
renderer geometry are presentation provenance unless explicitly promoted by release policy.

Validation dimensions are separate: canonical structure, cross-model semantics, notation semantics,
schema/syntax, renderer import/render and human/real-world correctness.

## C4 / Structurizr

C4 baseline:
- system landscape;
- system context;
- container.

Conditional:
- component;
- deployment;
- dynamic.

Code diagrams are excluded.

Only software-architecture-relevant canonical concepts map to C4. Do not force enterprise/process
concepts into C4.

Generated Structurizr requirements:
- deterministic element/relationship identifiers;
- explicit stable view keys;
- `!impliedRelationships false` or equivalent;
- canonical `ViewDefinition` owns semantic membership;
- tags/properties/static perspectives derive from canonical metadata;
- automatic layout baseline;
- manual layout, if supported, is separate `LayoutArtifact`;
- archetypes may reduce repetition but are not canonical ontology/type authority;
- dynamic URL/network perspectives are excluded;
- filtered views are not baseline for portable auto-layout output;
- no remote includes, scripts/plugins or duplicated narrative docs as semantic inputs.

Outputs are complementary:
- Structurizr static export = rich C4 consumption surface;
- PlantUML/SVG = portable embeddable representation.

## ArchiMate

Maintain a versioned `ArchiMateMappingProfile`:
- canonical kind -> ArchiMate concept;
- conditional/unmapped cases;
- canonical relationship -> ArchiMate relationship;
- required relationship modifiers;
- source/target relationship-validity matrix;
- profile version.

Validate semantic relationship legality before export.

Generate **model-level Open Group ArchiMate Exchange XML** as interoperability output:
- stable model/elements/relationships;
- names/descriptions;
- relationship modifiers;
- properties/property definitions;
- optional organization/folder metadata.

Baseline defers exchange-format diagram geometry.

Exchange XML is never persistent authoring source. Any future external-tool import stages, resolves
stable IDs, computes semantic diff and requires review.

Generate PlantUML ArchiMate separately for visual views. Exchange XML and PlantUML share canonical
notation bindings but have distinct technical purposes.

Qualification: XSD validation, stable IDs and independent import into Archi (or another conforming
implementation) without loss of baseline model semantics.

## PlantUML

Use the explicitly selected **MIT distribution**, not an arbitrary main-repository build.

Supported roles:
- ArchiMate visuals;
- UML sequence;
- UML state;
- selective UML class;
- implementation/schema-derived IE/ERD;
- portable Structurizr export.

Rules:
- aliases derive from notation bindings, never display names;
- centralized style/theme profile;
- optional hyperlinks/tooltips are presentation only;
- restrictive security profile;
- no remote includes;
- bounded local subprocess execution;
- syntax/failfast check + SVG existence/parsing + structured diagnostics.

Graphviz is current layout baseline. Smetana is a qualification candidate; switching layout engine
is a renderer/layout change, not semantic architecture drift.

## BPMN

Canonical workflow semantics remain in typed domain behavior models.

Keep **semantic BPMN XML** separate from **BPMN DI/layout**. Layout-only changes must not appear as
workflow semantic changes.

Versioned `BPMNProfile` enumerates the supported subset. Initial target includes:
- process/collaboration;
- participants/pools/lanes;
- common task types;
- start/end/intermediate events;
- exclusive/parallel/inclusive gateways;
- subprocesses;
- sequence/default/conditional flows;
- message flows;
- boundary events;
- data objects/stores/associations;
- text annotations;
- groups only if the qualified layout pipeline supports them.

Unsupported constructs fail or warn explicitly; never silently downgrade semantics.

Pipeline:

```text
canonical workflow
 -> Python/lxml semantic BPMN XML
 -> OMG XSD validation
 -> bpmn-moddle interoperability parse/write check
 -> bpmnlint correctness rules
 -> bpmn-auto-layout candidate -> BPMN DI
 -> bpmn-js local import/render
 -> portal view / optional static export
```

Semantic and DI IDs are deterministic notation bindings.

`bpmnlint:correctness` is the candidate technical lint layer. Opinionated/recommended rules remain
advisory until explicitly adopted.

`bpmn-auto-layout` is the preferred DI candidate but remains qualification-gated for subset
coverage, deterministic output, layout quality and packaging. It intentionally regenerates DI.

bpmn-js is the preferred local interactive viewer. Baseline does not make browser edits a source.
Preserve the required bpmn.io watermark.

bpmn-to-image/Puppeteer/Chromium is optional milestone export capability, not baseline runtime.

If Node tooling is adopted, pin one vendor runtime/dependency lock under the existing tool bootstrap;
do not create a second application or persistent service by default.

## UML and ERD

Use UML selectively:
- sequence for ordered runtime interactions;
- state for lifecycle/state behavior;
- class only when implementation/domain structure materially benefits.

BPMN remains workflow authority.

ERD comes from actual implementation/storage schemas and must preserve relevant:
- entities/tables;
- field IDs/names/types;
- primary/unique keys;
- foreign keys;
- nullability;
- cardinality/optionality.

Do not infer database cardinality from generic architecture relationships.

## Rendering and provenance

Target deterministic:
- canonical model;
- view membership;
- notation bindings;
- mapping profiles;
- generated notation source.

Renderer geometry may vary with engine/platform/font. Preserve renderer provenance rather than
requiring byte-identical SVG across supported platforms.

Every vendor invocation:
- runs locally by default;
- receives generated local input;
- uses argument arrays, not shell interpolation;
- has a timeout/resource bound;
- captures stdout/stderr/warnings;
- records renderer/tool/layout versions.

Historical milestone artifacts are preserved when exact renderer-byte reproduction is not guaranteed.

## Portal

MkDocs remains the Python publishing engine. Target Material for MkDocs 9.x only after exact-version
lock/qualification.

Release portal is offline-first:
- strict build;
- local assets;
- local search;
- no analytics/comments/external runtime fonts/assets;
- stable routes based on canonical identities;
- downloadable/static directory/zip.

Recommended sections: overview, capabilities/outcomes, workflows, systems, interfaces, information,
deployment, notation views, traceability, impact analysis, releases/changes and decisions/references.

Generate stable detail pages for canonical objects/views/releases. Link detail pages to views and
traceability results.

Integrate:
- Structurizr static C4 experience as a generated subsite/artifact;
- local bpmn-js interactive views if qualified;
- portable SVG for ordinary embedding/export.

Portal output is generated consumption state, never editable architecture authority.

## Kroki

Deferred optional local adapter. If enabled:
- local/private deployment only by default;
- pinned version/image digest;
- restricted/safe configuration;
- remote includes disabled;
- BPMN companion explicitly provisioned;
- output compared with direct-renderer qualification.

No public Kroki endpoint processes confidential models by default.

## Release integration

ArchitectureRelease may pin:
- ViewDefinition digests;
- mapping-profile versions;
- ProjectionArtifact digests;
- preserved LayoutArtifact digests;
- preserved RenderArtifact digests;
- ValidationArtifact reports;
- portal bundle digest/toolchain provenance.

Change classification distinguishes canonical semantic, view-membership, notation-mapping,
layout-only, style/theme-only, renderer/toolchain and publication/navigation-only changes.
