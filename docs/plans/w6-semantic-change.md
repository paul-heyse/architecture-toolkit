# Wave 6 — Semantic change records and the operations surface

> Milestone: M3 · Requirements: DATA-26, DATA-28, DATA-38 · Depends on: W5

## Purpose

Explain what changed between two releases, in architectural terms, and expose the whole lifecycle
through one small API and CLI. Delta knows which files changed; this wave knows that an element was
renamed rather than deleted and re-added, that an interface contract changed, and that moving a
diagram box changed nothing semantic.

Three requirements, but not a small wave: DATA-26's change-set model and DATA-38's full verb set
are substantial. The hash this builds on already exists — W2 delivered it.

## Contract references

- [data.md § History and semantic diff](../contracts/data.md) — DATA-26, DATA-28.
- [data.md § Responsibility split](../contracts/data.md) — DATA-38, the API and CLI surface.
- [core.md § Pydantic domain](../contracts/core.md) — the change-command pipeline from W1.
- Record `ARCH-TOOL-DATA-001` §6 and §6B.

## Work items

1. **ArchitectureChangeSet** (DATA-26). Carries change set ID, base and new release IDs, author or
   agent identity, rationale, decision references, changed objects, validation results and
   impact-analysis results. Immutable once published.
2. **Change classification** (DATA-26). Distinguish at minimum: element added, retired, renamed;
   relationship added or removed; relationship endpoint changed; interface contract changed;
   requirement applicability changed; evidence or qualification changed; view or layout changed.
   **Moving a diagram box must not appear as an architectural redesign.**
3. **Diff computation** (DATA-26). Use the W5 DataFusion context for added, removed and changed-ID
   joins, and typed Python for field-level diffs within a changed record. The semantic hash from
   W2 decides what counts as changed; this wave decides how to describe it.
4. **Layout separation** (DATA-26, and PROJ-04 later). Layout and presentation changes are
   classified separately and never enter the semantic change narrative.
5. **CDF cross-check** (supports DATA-57, owned by W4). Compare the semantic diff against Delta
   change data feed row changes as a correctness cross-check on this implementation. The CDF result
   is never the narrative.
6. **Scenarios and alternatives** (DATA-28). A design alternative gets its own model or scenario
   identity plus an explicit baseline reference. Its existence does not imply it superseded or was
   selected over the current design, and it is not a later release of the baseline. Release history
   and alternative history are different relations.
7. **Operations API** (DATA-38). One small Python API covering the full lifecycle: load baseline,
   apply change set, validate, diff, review, persist, publish, output. This is the surface every
   later wave and any consumer uses.
8. **CLI verbs** (DATA-38). Extend `cli.py` beyond `doctor`, `validate`, `schema` and the reserved
   `build`. Register the complete verb set now; `output` returns a typed not-implemented
   `Diagnostic` until W8 completes it, in the same style as the current `build` stub. This wave's
   gate covers baseline, change, validate, diff, review, persist and publish.

## Hard gate

> Layout/presentation-only changes do not masquerade as semantic model changes.
> — [data contract](../contracts/data.md), History and semantic diff

Also required: a rename produces a rename, not a retire plus an add; an order-sensitive behavior
change is detected; scenario identity stays separate from release sequence.

## Policy only

None. Every requirement in this wave is a feature.

## Executable checks

```sh
uv run pytest -m "unit or integration"
uv run architecture diff --base <release> --candidate <release>
uv run pyrefly check
```

## Evidence

Requirement markers throughout. The four distinct-change cases from data.md §10C — a rename, an
interface modification, a relationship removal and a layout edit — are the qualification set and
must produce four visibly different classifications.

## Risks and open questions

- **Field-level diff granularity** inside a changed detail record: too coarse and the change set is
  useless, too fine and every publication is noisy. Start at the typed-field level.
- **Merging into W5.** The union of W5 and W6 is exactly M3's input list. They are kept apart
  because the gates differ and they own different packages, but merging is reasonable if the
  change-set model turns out small in practice.
- **CLI verb naming** is a durable public surface. Confirm the verb set with the owner before
  release; renaming later breaks consumers.
