# Agent handoff

## Establish context

Read the root contract, all three subsystem contracts and `reference/requirements.json`. Inspect
the working tree before changes. If authorized private context exists in
`.context/workspace.json`, read the linked Notion records; never commit those URLs or private
content.

The same capable programming agent can execute the milestones below. They are dependency gates,
not separate team handoffs.

Milestone `### Inputs` are **read scope**: an identifier may appear in several. Delivery scope is
one wave, recorded in `reference/plan-waves.json` and enforced by `scripts/check_plan_coverage.py`.
`docs/plans/` decomposes these milestones into individually reviewable waves; this file remains
authoritative for the gates.

## Current executable state

Implemented:
- one locked Python 3.14 uv environment;
- minimal strict Pydantic model and CLI;
- endpoint/identity checks;
- explicit-version Delta -> PyArrow -> DataFusion materialized adapter;
- synthetic examples and basic qualification tests;
- checksummed local Java/vendor bootstrap;
- handwritten PlantUML/Structurizr/BPMN smoke fixtures;
- MkDocs documentation scaffold and two-platform CI.

Not implemented:
- CORE domain/authoring/source-map architecture;
- coherent multi-table release manager;
- Dataset/stream SnapshotProviders;
- semantic diff/scenarios/GraphPolicy facade;
- generated ArchiMate/C4/BPMN/UML/ERD projections;
- interactive/offline portal integration;
- requirement-evidence plugin;
- Pyrefly migration.

D-032 selects Pyrefly as the target checker. Current executable checks still use ty until that
migration is committed.

## M1 — Domain and authoring

### Inputs
`docs/contracts/core.md`; CORE-01..21, CORE-53..65; DATA-03..14, DATA-29..33, DATA-35..36,
DATA-41; DATA-01..02.

### Required outputs
- semantic scalar types and discriminated domain/detail/command models;
- common Diagnostic and cross-record validator layer;
- generated JSON Schema contracts/snapshots;
- ruamel YAML authoring profile + SourceMap + source-aware diagnostics;
- typed immutable compiled records;
- versioned canonical semantic hash and record-level semantic diff (DATA-27);
- Hypothesis strategy library and dev/ci/deep profiles (CORE-45, CORE-47);
- registered pytest markers and the requirement-evidence report (CORE-48..52);
- EngineeringQualificationArtifact for static/engineering evidence (CORE-66);
- Pyrefly migration/config/Protocol fixtures per D-032;
- qualified Ruff profile changes only if useful.

The evidence substrate is listed here, not in M6, because it is the instrument every later
milestone gate is measured with. M6 retains CORE-46 and CORE-67 and the both-platform execution.

### Hard gates
- rename preserves identity;
- forbidden YAML constructs fail deterministically;
- nested validation resolves to source location;
- no normal validation bypass APIs;
- public API typing direction is explicit and clean under the pinned checker.

## M2 — Storage and coherent releases

### Inputs
M1; `docs/contracts/data.md`; DATA-10..14, DATA-19..25, DATA-34..37, DATA-39..60.

### Required outputs
- explicit Arrow schemas/mappings;
- SnapshotProvider interface preserving current materialized fallback;
- Python deltalake snapshots;
- immutable ArchitectureRelease manifest;
- lock, expected-parent, staging/readback and current pointer;
- commit provenance/idempotency qualification where supported;
- explicit migration/retention policy.

### Hard gates
Fault injection after every publication stage never exposes partial state. Stale parent fails.
Unchanged table versions can be reused. Retained historical releases remain readable.

## M3 — Queries, graph and semantic change

### Inputs
M2; DATA-15..18, DATA-26..29, DATA-38, DATA-46..50, CORE-22..31.

### Required outputs
- one release-scoped DataFusion SessionContext per manifest;
- versioned parameterized query recipes + expected result schemas;
- query-plan evidence for representative recipes;
- private ArchitectureGraph + GraphPolicy facade;
- explainable bounded path/SCC/DAG analyses;
- semantic diff and scenario comparison.

### Hard gates
DataFusion and NetworkX read the same release. Cross-release comparisons use explicit sides.
Parallel relationship IDs remain distinct. Reachability is never reported as certain failure.

## M4 — Projections and rendering

### Inputs
M1-M3; `docs/contracts/projections.md`; PROJ-01..34; CORE-32..44.

### Required outputs
- NotationBinding/ViewDefinition/Layout/Projection/Render/Validation artifact model;
- ArchiMate mapping/relationship profile + model-level Exchange XML + independent import test;
- generated Structurizr with explicit IDs/view keys, implied relationships disabled and static perspectives;
- PlantUML security/validation wrapper;
- BPMN supported profile, semantic XML, XSD/moddle/lint and qualified layout/render path;
- selective UML and schema-derived ERD.

### Hard gates
All notation IDs trace to canonical IDs. A renderer cannot create canonical semantics.
Semantic and layout changes remain distinguishable. Vendor handwritten fixtures do not count as
generated-projection acceptance.

## M5 — Portal and release exports

### Inputs
M4; PROJ-35..41; DATA-25, DATA-37.

### Required outputs
- exact-version qualified Material dependency if retained;
- offline strict MkDocs portal;
- stable generated detail/view/release routes;
- Structurizr static C4 artifact;
- local BPMN interactive view if qualified;
- self-contained milestone export with manifest/schemas/Parquet/permitted sources/outputs/notices.

### Hard gates
No external runtime assets/network calls are required for the canonical offline bundle. Live stores
are never synced.

## M6 — Cross-family qualification

### Inputs
All previous milestones; CORE-45..67, DATA-40..60, PROJ-42.

### Required outputs
- Hypothesis property strategies and release state machine;
- pytest requirement-evidence artifact;
- historical replay + schema migration tests;
- both-platform qualification;
- requirement coverage report and explicit remaining gaps.

### Done means
A synthetic vertical slice runs source -> validated model -> storage -> coherent release ->
relational/graph queries -> semantic change -> standards projections -> local renders -> offline
portal/export, with fault-injection and historical-replay evidence.

No schema validation, rendered picture, linter run or type check alone establishes tool completeness
or real-world model correctness.

## Current checks

Until D-032 is implemented:

```sh
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run ty check src
uv run pytest
uv run python scripts/check_schema.py
uv run python scripts/check_plan_coverage.py
uv run architecture validate examples/minimal/model.yaml
uv run --group docs mkdocs build --strict
uv run python scripts/bootstrap_tools.py
uv run python scripts/qualify_tools.py
```

After the Pyrefly migration, replace the ty command with the accepted Pyrefly check/coverage commands
and update CI/toolchain evidence in the same implementation PR.

Dependency/tool upgrades regenerate locks/pins and pass relevant macOS ARM64 + Linux x86-64
qualification. Never enable native Delta/DataFusion FFI merely because import/registration exists.
