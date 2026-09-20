# Wave 9 — Cross-family qualification and the vertical slice

> Milestone: M6 · Requirements: CORE-46, CORE-67; DATA-40, DATA-42; PROJ-42 · Depends on: W8

## Purpose

Prove the whole thing, on both supported platforms, and establish the discipline that stops the
toolkit being described as complete before it is. Five requirements, all of them about evidence
rather than features. This wave also lands the deferred acceptance that earlier waves could not
satisfy literally: the Hypothesis release state machine, full Protocol implementation, and the
strict public-API coverage target.

## Contract references

- [core.md § Hypothesis](../contracts/core.md) — CORE-46, the release state machine.
- [core.md § Engineering qualification artifact](../contracts/core.md) — CORE-67.
- [data.md § Cross-library qualification](../contracts/data.md) — DATA-40, the minimum type and
  interchange cases.
- [data.md § Responsibility split](../contracts/data.md) — DATA-42, the retained alternative.
- [projections.md § Rendering and provenance](../contracts/projections.md) — PROJ-42.
- [qualification.md](../qualification.md) — the current evidence matrix this wave replaces.
- Records `ARCH-TOOL-CORE-001` §12 and §17, `ARCH-TOOL-DATA-001` §10.

## Work items

1. **Release publication state machine** (CORE-46). A Hypothesis `RuleBasedStateMachine` over a
   simple reference model of publication state, driving W4's step-addressable API. Rules cover
   stage, fail, retry, stale parent, publish, migrate and historical read. Invariants: the current
   pointer always resolves to a complete release; a stale parent never publishes; unchanged table
   versions are reused; every retained release stays readable. Fault injection must reach every
   publication boundary. This is the generative counterpart to W4's deterministic fault-injection
   tests, not a replacement for them.
2. **Full cross-library matrix** (DATA-40). Execute every case from data.md through the complete
   path — Pydantic, PyArrow, deltalake write, exact Delta version, SnapshotProvider,
   release-scoped DataFusion, Arrow result — and track type fidelity, metadata fidelity, logical
   row equivalence, query correctness, batch independence, historical reproducibility and
   materialization behavior. W3 seeded the Arrow-only cases and W4 owns the matrix; this wave runs
   it whole.
3. **Historical replay and migration** (DATA-40). An earlier release remains queryable and its
   outputs reproducible, including across an intentional vN to vN+1 schema migration.
4. **Cross-tool identity parity** (PROJ-42). The same canonical IDs resolve consistently across
   generated Structurizr, ArchiMate Exchange, PlantUML and BPMN outputs. Where renderer bytes
   differ between platforms but sources and mappings are equal, record the renderer difference
   rather than treating it as architecture drift.
5. **Both-platform execution** (PROJ-42, CORE-67). Everything above runs on macOS ARM64 and Linux
   x86-64, the two targets CI already matrixes.
6. **Complete the Protocol boundaries** (CORE-58, deferred from W0). Every one of the eight
   Protocols has at least one non-trivial implementation statically verified against it.
7. **The vertical slice** (CORE-67). One synthetic model runs end to end: source, validated model,
   storage, coherent release, relational and graph queries, semantic change, standards projections,
   local renders, offline portal and export — with fault-injection and historical-replay evidence.
8. **Claim discipline** (CORE-67). A guard test scanning `README.md` and `docs/qualification.md`
   for completeness assertions, failing unless the evidence report shows every matrix case green on
   both platforms. This encodes the standing rule that no schema validation, rendered picture,
   linter run or type check alone establishes tool completeness.
9. **Retain the alternative** (DATA-42). A documented statement that immutable Parquet plus
   manifests remains a credible simpler design, and that substituting it is an architecture
   decision rather than a refactor. Paired with the DATA-02 guard from W0.
10. **Requirement coverage report** (CORE-67). Produce the coverage report over all 169
    requirements from the CORE-49 evidence artifact, and state the remaining gaps explicitly.
    Replace the hand-maintained matrix in `docs/qualification.md` with generated output.

## Hard gate

> A synthetic vertical slice runs source -> validated model -> storage -> coherent release ->
> relational/graph queries -> semantic change -> standards projections -> local renders -> offline
> portal/export, with fault-injection and historical-replay evidence.
> — [agent handoff](../agent-handoff.md), M6 "Done means"

## Policy only

CORE-67 and DATA-42 — claim discipline and a retained alternative, both enforced by guard tests
over documentation rather than by features.

## Executable checks

```sh
uv run pytest
uv run pytest -m "property and qualification" --hypothesis-profile=deep
uv run python scripts/check_plan_coverage.py
uv run python scripts/qualify_tools.py
uv run pyrefly check
uv run pyrefly coverage check
```

On both macOS ARM64 and Linux x86-64.

## Evidence

The output of this wave is the evidence artifact itself: a report conforming to
`schemas/qualification-evidence.schema.json` covering all 169 requirements, with toolkit commit,
platform, Python version, lock digest and per-test outcomes.

## Risks and open questions

- **"Done" is bounded.** Completing this wave establishes that the toolkit implements its own
  contracts. It does not establish that any modelled architecture is correct, nor consumer
  acceptance. Those are separate claims and must stay separate in the record.
- **Deep Hypothesis profiles are slow.** Keep them out of the default CI path and run them on a
  schedule or on demand, so the 15-minute CI timeout still holds.
- **Platform-divergent renderer output** is expected and explicitly not a failure. The matrix must
  distinguish a genuine semantic difference from a Graphviz version difference.
- **Requirement additions after this wave** are a two-file change: `reference/requirements.json`
  and the `minItems`/`maxItems` pin in `schemas/requirements.schema.json`, plus the partition in
  `reference/plan-waves.json`.
