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

1. **Pyrefly replaces ty** (CORE-53, CORE-54, CORE-55). *Landed.* `ty` and
   `[tool.ty.environment]` removed; `[tool.pyrefly]` configures `src`, `tests`, `scripts` under
   Python 3.14 with `required-version = ">=1.3.1,<1.4.0"`, which makes a mismatched checker a
   fatal configuration error rather than a silent behaviour change.
2. **Widen the checked surface** (CORE-57). *Landed.* CI ran `ty check src`; it now runs
   `pyrefly check` over source, tests and scripts. The migration needed no code change —
   Pyrefly reported 0 errors on the wider surface from the first run.
3. **Protocol registry** (CORE-58). *Landed.* `src/architecture_toolkit/domain/protocols.py`
   declares all eight boundaries named in core.md: `SourceLoader`, `SnapshotProvider`,
   `ProjectionGenerator`, `Renderer`, `ValidatorAdapter`, `Publisher`, `QueryExecutor`,
   `ArtifactStore`. Only
   `SourceLoader` and `ValidatorAdapter` are fully typed here — the rest exchange DTOs that do not
   exist until W1..W4. Add a test asserting the module is exhaustive against the contract list.
4. **Exhaustive dispatch helper** (CORE-59). *Landed.* The `match` + `assert_never` idiom, with
   a `tests/static/` fixture verified to fail when a union gains a variant.
5. **Pydantic and pytest static qualification** (CORE-56). *Landed.* `tests/static/` covers
   discriminated unions, constrained `Annotated` aliases, frozen strict models, `TypeAdapter` and
   `model_validator(mode="after") -> Self`. Seeded here; W1 and W2 must extend it as new patterns
   appear, or those patterns are unqualified.
6. **Type coverage ratchet** (CORE-61, CORE-62). *Landed.* `[tool.pyrefly.coverage] includes`
   narrows measurement to `src` while the check surface stays wide; CI enforces
   `--strict --fail-under 85`, the measured floor. `--public-only` is deliberately unused: it keys
   off underscore-prefixed *module* names rather than `__all__`, so it means nothing until W1
   adopts that convention. `pyrefly infer` never runs in CI.
7. **No baseline file** (CORE-60). *Landed.* No `baseline` key is set. Suppressions are narrow
   `# pyrefly: ignore[error-code]` comments; none is needed today.
8. **Marker taxonomy** (CORE-48). *Landed.* All nine markers registered, with
   `--strict-markers` and `xfail_strict`. An unregistered marker is now a collection error.
9. **Requirement-evidence plugin** (CORE-49, CORE-50). *Landed.* Emits a schema-conforming
   document under `.runtime/`; an unknown requirement ID fails collection. JUnit stays the
   standard CI channel and CI archives both per platform.
10. **Reconcile the vendor report** (CORE-49). *Re-scoped, not done.* The vendor report shares
    **zero** fields with `qualification-evidence.schema.json` and has no pytest node to name, and
    its `not_qualified`/`not_implemented` outcomes are absent from that enum. Vendor checks are
    engineering evidence, so they belong to `EngineeringQualificationArtifact` (CORE-66), whose
    `CheckResult` keeps those states. Migrating `qualify_tools.py` onto that model is W7b work,
    when generated projections replace the handwritten fixtures it currently checks.
11. **Fixture discipline** (CORE-51, CORE-52). *Landed.* `tests/conftest.py` holds typed
    function-scoped fixtures; all seven test functions now carry return annotations.
12. **Hypothesis profiles** (CORE-47). *Landed.* `dev`, `ci` and `deep` registered in
    `conftest.py`; `ci` is loaded by default. No network in any profile.
13. **Ruff expansion** (CORE-63, CORE-64, CORE-65). *Landed.* `RUF`, `PT`, `PTH`, `S` added to
    `E,F,I,UP,B`. Qualification against this tree found 14 findings in three clusters and nothing
    from `RUF`, `PT` or `PTH`, so the expansion costs exactly two per-file ignores: `S101` in
    `tests/**`, and `S603`/`S607` in `scripts/*.py` for the reviewed argv invocations that
    `rules/no-shell-invocation.yml` already blesses structurally.
14. **EngineeringQualificationArtifact** (CORE-66). *Landed.* `domain/engineering.py`, guarded
    against importing model validation. Its `CheckResult` keeps `not_qualified` and
    `not_implemented` distinct from `failed`: a capability never qualified is not a failure.
15. **Import-layering guard** (DATA-01, DATA-32). *Landed.* `queries-no-direct-delta` joins
    `domain-layer-imports` and `storage-no-graph-import`. Structural rules, not text patterns; the
    guard table is in [contract enforcement](../contract-enforcement.md).
16. **Dependency guards** (DATA-02, DATA-33, DATA-35). *Landed.* `check_boundaries.py` reads the
    resolved `uv.lock` so transitive pulls are caught. The DATA-02 constraint — that the stack is
    justified by typed interchange and coherent snapshots, not by volume, and that SQLite or
    Parquet-plus-manifests remain credible alternatives — is recorded in the guard table.
17. **Workspace boundary guard** (DATA-36). *Landed.* Private-marker scan over `git ls-files`
    plus a tracked-payload check rejecting `.runtime/`, `.tools/`, `.venv/`, `.context/` and
    `site/`. `check_boundaries.py` is now actually wired into CI — it was documented as running
    there but was not.

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
uv run python scripts/check_schema.py
uv run python scripts/check_plan_coverage.py
uv run python scripts/check_boundaries.py
ast-grep scan
ast-grep test
```

`uv run ty check src` is removed. The coverage floor is the measured `src` baseline; raise it as
annotated code lands and never lower it without a recorded reason.

## Evidence

Every test carries `@pytest.mark.requirement(...)` for the identifiers it evidences. The wave's own
output is the first `EngineeringQualificationArtifact`: Pyrefly check, Pyrefly coverage, Ruff check
and format, and the lock digest, on both macOS ARM64 and Linux x86-64.

## Risks and open questions

- **Pyrefly does not follow semantic versioning** and any release may introduce new diagnostics
  (D-032). The version is lock-controlled and upgrades are explicit engineering changes.
- **Pyrefly 1.3.1 remains current** and ships wheels for both target platforms. `required-version`
  pins it in config as well as in the lock.
- **pyarrow ships no `py.typed`**, so `pa.Schema` resolves to `Any` and
  `storage.datafusion_adapter.register_snapshot` is `[coverage-partial]`. That single symbol is the
  whole gap between 85.71% and 100% strict on `src`. `pyarrow-stubs` targets major 20 against the
  pinned 25 and is not adopted; revisit at W3.
- **`pyrefly init --migrate-from` supports only mypy and pyright**, so there is no automated ty
  migration path. The config is hand-written and reviewed.
- **Stub packages are dev-only typing aids** with no runtime surface, so they do not create an
  overlapping data stack under DATA-32/33 — but `types-lxml` pulls `soupsieve`, `types-html5lib`
  and `types-webencodings` transitively, which the DATA-33 deny-list review should acknowledge.
