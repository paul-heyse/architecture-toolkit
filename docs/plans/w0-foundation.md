# Wave 0 — Foundation: toolchain, evidence substrate and boundary policy

> Milestone: M1 · Requirements: CORE-47..CORE-66; DATA-01, DATA-02, DATA-32, DATA-33, DATA-35,
> DATA-36 · Depends on: nothing

## Purpose

Put the measuring instruments in place before there is anything to measure. When this wave lands
the repository type-checks under Pyrefly rather than ty, pytest registers the full marker taxonomy
and emits a machine-readable requirement-evidence report, and the architectural boundaries that
every later wave must respect are enforced by guard tests rather than by prose. Nothing in the
domain model changes.

Doing this first is a deliberate reversal of `ARCH-TOOL-CORE-001` §19, which sequences the Pyrefly
cascade last as C6. The repository's own M1 already lists the migration as an M1 output, and
settling the checker before the typed domain layer exists avoids retrofitting annotations across
every package.

## Contract references

- [core.md § Pyrefly target](../contracts/core.md) — CORE-53..CORE-62; decision D-032.
- [core.md § Ruff](../contracts/core.md) — CORE-63..CORE-65.
- [core.md § pytest evidence](../contracts/core.md) — CORE-48..CORE-52.
- [core.md § Hypothesis](../contracts/core.md) — CORE-47.
- [core.md § Typed subsystem interfaces](../contracts/core.md) — CORE-58.
- [core.md § Engineering qualification artifact](../contracts/core.md) — CORE-66.
- [data.md § Responsibility split](../contracts/data.md) — DATA-01, DATA-32, DATA-33.
- [implementation-contract.md § Package boundaries](../implementation-contract.md) — the table the
  import-layering guard is generated from.
- Records `ARCH-TOOL-CORE-001` and `ARCH-TOOL-SETUP-001`; decision D-032.

## Work items

1. **Pyrefly replaces ty** (CORE-53, CORE-54, CORE-55). Remove the `ty` dev dependency and
   `[tool.ty.environment]`; add a reviewed pinned Pyrefly to the `dev` group; add `[tool.pyrefly]`
   with `project-includes = ["src", "tests", "scripts"]`, `search-path = ["src"]`,
   `python-version = "3.14"`, `check-unannotated-defs = true` and excludes for `.tools/`,
   `.runtime/`, `site/`. Regenerate `uv.lock`. Never unconfigured or basic mode.
2. **Widen the checked surface** (CORE-57). CI currently runs `ty check src`. Replace with a
   Pyrefly check over source, tests and scripts — `scripts/*.py` and `tests/` are unchecked today.
3. **Protocol registry** (CORE-58). Add `src/architecture_toolkit/domain/protocols.py` declaring all
   eight boundaries named in core.md: `SourceLoader`, `SnapshotProvider`, `ProjectionGenerator`,
   `Renderer`, `ValidatorAdapter`, `Publisher`, `QueryExecutor`, `ArtifactStore`. Only
   `SourceLoader` and `ValidatorAdapter` are fully typed here — the rest exchange DTOs that do not
   exist until W1..W4. Add a test asserting the module is exhaustive against the contract list.
4. **Exhaustive dispatch helper** (CORE-59). Establish the `match` + `assert_never` idiom and a
   fixture proving a new union member produces a static failure.
5. **Pydantic and pytest static qualification** (CORE-56). Add `tests/static/` fixtures for the
   advanced Pydantic patterns core.md relies on — discriminated unions, `Annotated` constrained
   aliases, frozen models, `TypeAdapter`. Seeded here; W1 and W2 extend it as new patterns appear.
6. **Type coverage ratchet** (CORE-61, CORE-62). Wire `pyrefly coverage check` / `report`, record
   the baseline, and fail on a decrease. `pyrefly infer` never mutates source in CI.
7. **No baseline file** (CORE-60). Do not commit a Pyrefly baseline. If one is needed transiently
   for the migration, add a CI check for stale entries and a removal plan.
8. **Marker taxonomy** (CORE-48). Register `unit`, `property`, `integration`, `interop`, `vendor`,
   `qualification`, `platform`, `slow` and `requirement` in `[tool.pytest.ini_options]`, and add
   `--strict-markers`. None are registered today.
9. **Requirement-evidence plugin** (CORE-49, CORE-50). Add `tests/plugins/requirement_evidence.py`
   emitting a report conforming to `schemas/qualification-evidence.schema.json`. Validate every
   `requirement` marker value against `reference/requirements.json` and error on an unknown ID.
   Keep JUnit as the standard CI channel; the evidence report is separate.
10. **Reconcile the vendor report** (CORE-49). `scripts/qualify_tools.py` writes a fixed-key
    `report.json` that does not match the evidence schema. Bring it onto the same schema.
11. **Fixture discipline** (CORE-51, CORE-52). Add `tests/conftest.py` with typed fixtures at the
    narrowest practical scope; set `xfail_strict = true`.
12. **Hypothesis profiles** (CORE-47). Register `dev`, `ci` and `deep` with deliberate
    `max_examples`, stateful step counts and deadlines. No network in any profile.
13. **Ruff expansion** (CORE-63, CORE-64, CORE-65). Keep `E,F,I,UP,B` at py314/100 columns; qualify
    `RUF`, `PT`, `PTH`, `S` against the current tree and adopt with narrow per-file ignores
    (`S101` in tests; reviewed exceptions for the `subprocess` calls in `scripts/`). Preview off,
    no unsafe fixes in CI.
14. **EngineeringQualificationArtifact** (CORE-66). Model it in `domain/` with the fields core.md
    names. A guard test asserts it shares no type with the architecture `Diagnostic` and that
    neither module imports the other — engineering evidence never becomes model validation.
15. **Import-layering guard** (DATA-01, DATA-32). Generate a test from the Package boundaries table:
    `domain` imports none of pyarrow, deltalake, datafusion or networkx; `storage` does not import
    networkx; `queries` reaches Delta only through the storage adapter.
16. **Dependency guards** (DATA-02, DATA-33, DATA-35). Assert against the resolved `uv.lock`, not
    `pyproject.toml`, so transitive pulls are caught: no pandas, polars, duckdb, sqlalchemy, spark,
    a graph or vector database, or an orchestrator. One project, one lock, one environment.
17. **Workspace boundary guard** (DATA-36). Assert no private workspace URL and no `.runtime/` or
    `.tools/` payload is tracked by Git.

## Hard gate

> public API typing direction is explicit and clean under the pinned checker.
> — [agent handoff](../agent-handoff.md), M1 hard gates

## Policy only

CORE-50, CORE-60, CORE-62, CORE-65, DATA-01, DATA-02, DATA-32, DATA-33, DATA-35, DATA-36. Each is a
documented constraint plus a guard test. No feature is built for them.

## Deferred acceptance

Three requirements land here but cannot be literally satisfied yet; `reference/plan-waves.json`
records this under `deferred_acceptance`.

| ID | Delivered here | Literal acceptance from |
| --- | --- | --- |
| CORE-56 | Pyrefly/Pydantic harness seeded with known patterns | W2 |
| CORE-58 | Exhaustive Protocol registry, two fully typed | W9 |
| CORE-61 | Coverage measurement and non-decreasing ratchet | W7a |

CORE-61's deferral is the contract's own: core.md targets 100% strict public-API coverage
"after core API stabilization".

## Executable checks

```sh
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run pyrefly coverage check
uv run pytest --strict-markers
uv run python scripts/check_plan_coverage.py
```

`uv run ty check src` is removed from CI in the same change. Until that change is committed, ty
remains the repository's executable truth.

## Evidence

Every test carries `@pytest.mark.requirement(...)` for the identifiers it evidences. The wave's own
output is the first `EngineeringQualificationArtifact`: Pyrefly check, Pyrefly coverage, Ruff check
and format, and the lock digest, on both macOS ARM64 and Linux x86-64.

## Risks and open questions

- **Pyrefly does not follow semantic versioning** and any release may introduce new diagnostics
  (D-032). The version is lock-controlled and upgrades are explicit engineering changes.
- **Pyrefly 1.3.1 was the version reviewed** at decision time. Confirm the current release still
  supports Python 3.14 and the pinned Pydantic before committing the lock.
- **Ruff `S` on `scripts/`** will flag the `subprocess` calls in `bootstrap_tools.py` and
  `qualify_tools.py`. Those are reviewed argument-array invocations; prefer a narrow per-file ignore
  with rationale over dropping the rule family.
- **Adding `jsonschema`** to validate the evidence report is a deliberate dependency decision under
  DATA-32, not a free change. Decide whether the plugin validates in-process or CI validates the
  emitted artifact.
