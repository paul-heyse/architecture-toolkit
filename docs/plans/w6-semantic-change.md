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

## Decisions taken during execution

Recorded here because a wave plan that only says what was intended is unreadable next to the code
that resulted. Four of these were put to the owner before implementation; the rest were forced by
measurement.

### The change layer is its own package

`changes/` sits above `releases/` and `queries/`, imported only by `cli.py` and `contracts.py`.
W5 made `queries/` import `releases/`, so a change record living in `releases/` — where
[the plan index](index.md) said diff and classification would go — structurally could not carry the
`TraversalResult` that DATA-26's "impact-analysis results" requires. The alternative was a
locally-invented impact summary populated only by the CLI, which is the declared-but-unreachable
shape W5.1 spent a wave removing. `rules/changes-not-imported-by-lower-layers.yml` and
`tests/unit/test_layering.py` hold the direction.

### The narrative is computed from two models, and the engines cross-check it

`ARCH-TOOL-DATA-001` §6A asks DataFusion for the added/removed/changed-ID joins, and the first plan
made the `semantic_identity_delta` recipe the source. That is wrong for a reason the contract
itself supplies: §9C previews the diff **before** persist and publish, and CORE-20 presents one
after a round-trip authoring edit. In both, the candidate is unpublished, so a release-scoped engine
cannot be the narrative's source without making the preview impossible. The recipe and the Delta
change feed are therefore both cross-checks — which is the standing §11H already gives the feed
("Do not use them as the architectural change narrative") — and `identity_disagreements` and
`storage_disagreements` are library functions on the `diff --cross-check` path rather than
assertions living in tests.

### Classification is keyed by field, not by record

Measured rather than argued. A rename and an interface modification are **identical** one level up
— both are `elements: changed` — and only the field separates them. `NotationBinding` forced it from
the other side: it carries three natures across its own fields, so a per-record rule would either
make moving a box into another view an architectural change or make a `mapping_profile_version`
bump invisible, and `domain/notation.py` says DATA-31 forbids both.

Path-keying was rejected: paths are open (`detail.fields.<any field_id>.nullability`), so "total
over paths" is not definable without a glob language, and the totality assertion would degrade into
"every path some test happened to exercise".

### Two axes, and seven natures

`ChangeKind` says what changed; `ChangeNature` says whether it enters the narrative.
`projections.md` already names seven natures and W7a/W8 deliver the records that make the last two
reachable, so defining the wider set now means a later wave extends the table instead of migrating
every stored record. `STYLE_THEME_ONLY` and `PUBLICATION_NAVIGATION_ONLY` are asserted to be used by
nothing, in both directions.

### There is a residual, and it is guarded rather than avoided

`Reference.authority` and its kind have no named category in any contract, so `FIELD_MODIFIED`
exists. What keeps it from swallowing the table is that it is never a lookup default — an ast-grep
rule forbids `.get` on the three tables — plus a pinned ceiling *and* a list of seventeen fields
that must never reach it, because a bare count is gameable by adding rows elsewhere.

### An alternative gets an identity, not a position

DATA-28's teeth are in the refusals. `scenario_id` and `baseline_release_id` are set together or
not at all; a scenario whose *parent* is its baseline is refused at the record; a scenario whose
parent sits on another line is reported by `alternative_line_breaks`; `diff_releases` refuses a
cross-line pair and names the operation that is right for it; and `AlternativeComparison` is
deliberately not a `ModelChanges` and does not contain one, so it cannot be published as a change
set even by accident.

Physical separation needed no new machinery: one store has one current pointer and overwrites its
tables wholesale, so an alternative is published into its own store root, which `--store` already
provides. `compare_alternative` therefore takes **two** stores — the test found that, because a
one-store signature silently read the baseline twice and reported that the alternative differed
from its baseline in nothing.

### `persist` is a verb, and `output` is typed

`publish` iterates all eight `STEP_ORDER` names, so a partial `steps` mapping raises `KeyError`;
`PERSIST_STEPS` is the protocol minus its eighth line. What that leaves is a written, unexposed
manifest — the state DATA-24 permits after a crash and `recovery.resume` already knows how to
finish. `output` returns a typed `OutputNotImplemented` because
[W8's plan](w8-portal-export.md) says it will "replace the typed not-implemented diagnostic" and
expects one to exist.

### Corrections to this document

Three claims in the sections above were stale or wrong when the wave started, and are corrected
rather than quietly worked around:

- **The CLI was not `doctor`, `validate`, `schema` and `build`.** W4 and W5.1 had taken it to
  seventeen verbs, two of which — `validate` and `publish` — are DATA-38's own. W6 adds the other
  six.
- **`build` is not a typed not-implemented `Diagnostic`.** It is a bare
  `parser.exit(EXIT_USAGE, ...)` with no dispatch branch. `output` is typed because W8 expects it
  to be; `build` keeps its older stub, and the inconsistency is recorded here rather than
  normalised in passing.
- **`data.md` has no §10C.** The four qualification cases are §10C of the private record
  `ARCH-TOOL-DATA-001`: *"A rename, interface modification, relationship removal and diagram-layout
  edit must produce distinct semantic changes."* `tests/integration/test_change_gate.py` asserts
  the four classifications are pairwise distinct **and** pins the expected value of each, because
  distinctness alone is satisfiable by four residuals with different paths.

## Known state carried forward

- **Four of the seven natures have little or no data behind them.** `LAYOUT_ONLY` has two fields
  and `RENDERER_TOOLCHAIN` one; `STYLE_THEME_ONLY` and `PUBLICATION_NAVIGATION_ONLY` have none
  until W7a and W8. Declared with an explicit reason rather than omitted.
- **`NotationBinding` still participates in `model_digest`.** That is W2's decision and W6 does not
  change it: a binding edit *is* a model change. What W6 adds is that a binding's presentation
  fields never enter the narrative. Moving bindings out of the digest would be a DATA-56
  hash-version migration.
- **`context_id` is still written by nothing**, carried forward from W5 unchanged.
- **`require_review` is a caller's flag, not a policy record.** Nothing in the contracts says which
  changes need review, and inventing a record would be a governance claim no contract makes.
