# Core contract

Normative implementation contract for Pydantic, authoring/source mapping, diagnostics, NetworkX,
Jinja/lxml generation and engineering qualification. Requirements: **CORE-01..CORE-67**.

## Pydantic domain

### Required capabilities

- `ConfigDict(strict=True, extra="forbid")` baseline.
- Central `Annotated` semantic types for IDs, digests, schema/profile versions and qualified kinds.
- Field-discriminated unions for stable domain variants: detail records, change commands,
  references and artifact/finding variants.
- `TypeAdapter` for natural unions/collections; do not create wrapper models solely for validation.
- Validators limited to record-local invariants and explicit deterministic validation context.
- Structured custom error codes/context normalized into the common `Diagnostic`.
- Frozen compiled/published records plus immutable nested value types where semantic immutability matters.
- Generated/versioned JSON Schema for authoring, commands, manifests and other machine-facing contracts.
- Validation/serialization schema modes only where intentionally different.

### Mutation

```text
validated baseline + typed ChangeCommand(s)
 -> candidate construction
 -> complete Pydantic validation
 -> cross-record validation
 -> immutable candidate
```

Normal domain flow must not use `model_construct()`, `SkipValidation`, unvalidated in-place
mutation or `model_copy(update=...)` as the architecture mutation mechanism.

## YAML authoring

Use a single configured ruamel.yaml round-trip authoring adapter:

- YAML 1.2 semantics.
- Comments/quotes/source order preserved where practical.
- Explicit bounded depth and deterministic output settings.
- Duplicate keys are hard errors.
- Baseline forbids anchors/aliases, merge keys, custom application tags and unsafe Python tags.
- ruamel-specific objects stop at the authoring boundary; domain/storage logic receives plain data.

Build a `SourceMap` before domain conversion:

```text
SourceLocation:
  source/file ID
  document ID
  semantic path
  line/column
  optional end line/column

SourceMap:
  source digest
  parser/profile version
  semantic path -> SourceLocation
  canonical ID + field path -> SourceLocation after ID resolution
```

Round-trip source edits locate a semantic field, edit the presentation tree, serialize, reparse,
fully revalidate and present a semantic diff. Comments/quotes/whitespace do not enter semantic hashes.

## Diagnostics and cross-record validation

Common shape:

```text
Diagnostic:
  diagnostic_id
  code
  severity
  category
  message
  canonical_object_id?
  relationship_id?
  field_path?
  source_location?
  notation_object_id?
  validator/rule_id?
  context
  remediation?
```

Cross-record validators are pure with respect to the candidate. Rule families include ID
resolution/uniqueness, relationship endpoint semantics/cardinality, containment/acyclic rules,
evidence/reference links, schema/interface consistency, workflow references, view membership and
release/profile constraints.

Differentiate hard structural errors, evidence gaps, profile expectations and human/real-world review.

## NetworkX analysis

Build one private `MultiDiGraph` from one candidate/release:

- node key = canonical object ID;
- edge key = canonical relationship ID;
- minimal traversal attributes only; hydrate rich records from canonical tables/registries;
- raw graph is encapsulated behind an `ArchitectureGraph` facade.

`nx.freeze()` is only a structural guard: node/edge attribute dictionaries remain mutable.

Versioned `GraphPolicy` declares:

```text
policy_id/version
allowed relationship types
direction
allowed/excluded node kinds
context filters
max depth
max paths
max results
stop kinds
cycle handling
```

Use read-only filtered `subgraph_view` projections where suitable. Explainable path results retain
ordered node IDs, relationship IDs/types, release and policy version.

Use selectively:
- ancestors/descendants;
- bounded `all_simple_edge_paths`;
- cycle detection;
- strongly connected components + condensation;
- topological operations;
- transitive closure/reduction on validated DAG semantics.

Never enumerate unrestricted paths. Transitive reduction/closure are derived analysis, not canonical
relationship replacements. Generic centrality/community scores are deferred until a concrete
interpretive question justifies them.

## Typed subsystem interfaces

Prefer structural `Protocol` boundaries where implementations are replaceable:

```text
SourceLoader
SnapshotProvider
ProjectionGenerator
Renderer
ValidatorAdapter
Publisher
QueryExecutor (if needed)
ArtifactStore (only if multiple stores actually exist)
```

Protocols exchange typed DTOs/Pydantic models rather than arbitrary dictionaries.

## Jinja2 text generation

Jinja is a bounded textual renderer for Structurizr DSL, PlantUML and generated Markdown.

Required environment:
- centralized construction;
- `StrictUndefined`;
- controlled package/filesystem template root;
- explicit trim/lstrip/newline/trailing-newline behavior;
- deterministic pure filters/tests;
- no ambient time/random/environment/network/filesystem queries.

Pipeline:

```text
canonical release -> Python projection builder -> complete typed DTO -> Jinja -> text
```

Templates do not traverse NetworkX/DataFusion, infer relationships, select semantic view membership
or fetch evidence.

During qualification parse templates and use `meta.find_undeclared_variables` to compare template
requirements with allowed context/globals. Record the transitive template bundle digest, including
included/inherited macros.

Baseline templates are trusted checked-in code. Consumer-supplied templates require a separate
sandbox/resource model. **Do not generate standards XML with Jinja.**

## lxml standards XML

lxml owns BPMN and ArchiMate Exchange XML.

Required:
- namespace-aware `QName` / `ElementMaker`;
- central namespace registry;
- secure parser: no network, no DTD loading, external entity resolution disabled, no huge-tree
  override, no recovery for canonical validation;
- local checksummed resolver for schema import/include dependencies;
- `XMLSchema` validation and error-log normalization to `Diagnostic`;
- versioned XPath qualification assertions;
- literal source digest plus C14N digest where relevant.

For BPMN retain a semantic XML/C14N identity before DI where useful; combined semantic+DI has its
own projection/layout digest. Pretty-printing is presentation only.

Schematron, XSLT and incremental parsing are deferred absent a concrete standards requirement.

## Hypothesis

Maintain reusable strategies grouped by domain: IDs, records, relationships, workflows, views,
commands, releases and artifacts.

- Build valid data directly where possible; avoid filter-heavy strategies.
- Maintain invalid-by-one-rule strategy families.
- Bound recursive structures.
- Property families include authoring/semantic round trips, stable rename, presentation-independent
  hashing, graph edge identity, template determinism, XML C14N and release-history readability.

Use `RuleBasedStateMachine` for release publication. Exercise stage/fail/retry/stale-parent/
publish/migrate/historical-read operations with invariants from the data contract.

Use explicit `dev`, `ci` and `deep` profiles. `event()` records scenario coverage; `target()`
is reserved for meaningful complexity metrics.

## pytest evidence

Registered marker taxonomy:

```text
unit
property
integration
interop
vendor
qualification
platform
slow
requirement("CORE-xx" | "DATA-xx" | "PROJ-xx")
```

A local pytest plugin/hook emits a separate machine-readable requirement-evidence artifact with
test node ID, requirement IDs, outcome, platform, commit and relevant tool/dependency versions.

JUnit remains ordinary CI output. Do not make nonstandard JUnit properties the canonical evidence channel.

Fixtures are typed and use the narrowest practical scope. Use deterministic local fault injection
(`tmp_path`, `monkeypatch`, controlled wrappers). Known limitations use strict xfail with an
upstream/version reason.

## Pyrefly target

D-032 selects Pyrefly, and the migration has landed. `ty` and `[tool.ty.environment]` are
gone; what follows describes the configuration in force rather than a target.

Target configuration:
- explicit `[tool.pyrefly]`;
- Python 3.14;
- check `src`, `tests` and executable `scripts`;
- explicit source/search/exclusion configuration;
- no unconfigured/basic mode.

Required use:
- qualify every advanced Pydantic pattern used by the domain;
- type-check pytest fixtures/tests;
- enforce subsystem `Protocol` compatibility;
- use explicit discriminated-union narrowing and `assert_never`-style exhaustiveness where critical;
- no baseline file by default for this greenfield toolkit;
- only narrow reviewed error-code suppressions;
- target 100% **strict** type coverage for the public package API after interfaces stabilize;
- track whole-`src` strict coverage as engineering evidence.

Pyrefly versions are lock-controlled. Its release policy does not guarantee that new diagnostics
wait for strict semver-breaking releases, so upgrades require normal both-platform qualification.
`pyrefly infer` may assist local edits but never mutates source automatically in CI.

## Ruff

Keep Python 3.14 target and baseline `E,F,I,UP,B`. Qualify adding `RUF,PT,PTH,S`; enable only
with narrow reviewed exceptions. Preview behavior is off by default. CI runs lint and format checks,
never unsafe automatic fixes.

## Engineering qualification artifact

Source-code/tooling evidence is separate from architecture-model validation:

```text
EngineeringQualificationArtifact:
  artifact_id
  toolkit_commit
  python_version
  platform
  lock_digest
  check_type
  tool/tool_version
  configuration_digest
  result
  report_locator/report_digest
```
