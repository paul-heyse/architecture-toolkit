# Toolchain

Exact executable dependency state is governed by `uv.lock` and `tools.lock.json`. Contracts may
select a **target** capability before the dependency/config migration is implemented; current versus
target is explicit below.

## Python

Python 3.14.7; uv 0.12.7; one project, lock and environment.

| Library/tool | Current state | Contract role / target |
| --- | --- | --- |
| Pydantic | installed | strict domain/commands/manifests, discriminated variants, JSON Schema |
| PyArrow | installed | explicit schemas, typed batches/streams/Dataset interchange |
| deltalake | installed | Python-only versioned table persistence/history |
| DataFusion | installed | release-scoped relational queries and plan evidence |
| NetworkX | installed | disposable policy-driven MultiDiGraph analysis |
| ruamel.yaml | installed | round-trip YAML authoring and source locations |
| Jinja2 | installed | strict deterministic textual projection rendering |
| lxml | installed | secure namespace-aware XML, schema validation and C14N |
| Hypothesis | installed | property and state-machine qualification |
| pytest | installed | test orchestration and future requirement evidence |
| Ruff | installed | lint/format; target selective RUF/PT/PTH/S expansion |
| ty | **currently installed** | current checker only; D-032 selects replacement |
| Pyrefly | **target, not installed** | Pydantic/pytest-aware type checks, Protocols, strict type coverage |
| MkDocs | installed docs group | offline portal engine |
| Material for MkDocs | target, unpinned | portal theme after exact-version qualification |

Use `uv sync --locked --all-groups`.

### Pyrefly migration boundary

Do not edit documentation to imply Pyrefly is executable until the implementation PR:
- removes ty dependency/config/checks;
- adds reviewed Pyrefly dependency/config;
- regenerates `uv.lock`;
- checks source/tests/scripts under Python 3.14;
- qualifies advanced Pydantic + pytest behavior and both target platforms.

## DataFusion / Delta compatibility

The current qualified baseline materializes a specifically selected Delta version to PyArrow before
DataFusion registration. Under the current scaffold lock, direct native FFI is incompatible.
The data contract defines Dataset/stream/native provider candidates; none may replace the fallback
without exact-stack qualification.

## Vendor tools

Run `uv run python scripts/bootstrap_tools.py`. `tools.lock.json` pins URLs, versions and SHA256
checksums. Downloads stay in ignored `.tools/`; bootstrap does not start services or modify system Java.

| Tool | Current pin | Use |
| --- | --- | --- |
| Temurin JRE | 21.0.12.1+1 | local Java runtime |
| PlantUML MIT build | 1.2026.8 | ArchiMate/UML/ERD and portable SVG |
| Structurizr unified WAR | 2026.06.28 | C4 validate/export; future static rich C4 artifact |
| OMG BPMN XSD set | BPMN 2.0.2 | local XML Schema validation |
| Graphviz | host package, version recorded | current PlantUML layout |

Install Graphviz with the platform package manager. It is not currently pinned identically across
platforms; rendered SVG bytes are not semantic architecture identity.

## Target projection additions

Qualification-gated, not currently installed/pinned by this document:
- ArchiMate Exchange XSD set/local resolver;
- bpmn-moddle;
- bpmnlint correctness rules;
- bpmn-auto-layout;
- bpmn-js local viewer;
- optional bpmn-to-image;
- one pinned Node runtime/tool bundle if the BPMN stack requires it;
- Material for MkDocs 9.x;
- optional local Kroki adapter only if it simplifies operations.

Node tooling, if adopted, remains vendor tooling under the same project bootstrap model, not another
application/project or persistent service by default.

## Security

- local/private rendering by default;
- no remote PlantUML/Structurizr includes in generated baseline;
- XML parser/resolver never fetches network schemas at validation time;
- bounded subprocesses with argument arrays and captured diagnostics;
- no public Kroki or other renderer endpoint for confidential models by default.

## Upgrade process

1. review accepted contract and affected requirements;
2. update one dependency/tool family deliberately;
3. regenerate Python lock or vendor pin/checksum;
4. run targeted interoperability tests;
5. run both-platform qualification where relevant;
6. record changed capabilities/limitations in qualification/handoff;
7. keep historical release/tool provenance intact.

Do not check downloaded binaries, extracted tools, runtime stores or caches into Git.
