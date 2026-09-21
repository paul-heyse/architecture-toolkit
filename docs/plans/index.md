# Implementation plans

Execution sequencing for the acceptance index. The milestones M1..M6 in
[agent handoff](../agent-handoff.md) remain the authoritative dependency gates; the waves below are
a finer decomposition of them into individually reviewable units.

These documents **sequence** work. They are not normative. Where a rule is needed, the wave cites
the governing section of [core](../contracts/core.md), [data](../contracts/data.md) or
[projections](../contracts/projections.md) and the requirement ID. A plan never overrides a
contract, and a plan is never evidence that a requirement is satisfied.

## Scope rule

Milestone `### Inputs` lists are **read scope**: an identifier may appear in several, and
DATA-10..14, DATA-25, DATA-37 and CORE-53..65 legitimately do. Wave assignment is **delivery
scope**: every identifier is owned by exactly one wave.

`reference/plan-waves.json` records the partition and `scripts/check_plan_coverage.py` enforces it.
The checker fails on an unassigned identifier, a double assignment, a forward dependency, a plan
document that never mentions an identifier it owns, and a quoted hard gate whose text no longer
appears in the contract it cites.

## Waves

| Wave | Milestone | Document | Requirements | n |
| --- | --- | --- | --- | --- |
| W0 | M1 | [Foundation](w0-foundation.md) | CORE-47..66; DATA-01, 02, 32, 33, 35, 36 | 26 |
| W1 | M1 | [Core schemas](w1-core-schemas.md) | CORE-01..13, 45; DATA-03..09, 29..31, 41 | 25 |
| W2 | M1 | [Authoring](w2-authoring.md) | CORE-14..21; DATA-27 | 9 |
| W3 | M2 | [Arrow fabric](w3-arrow-fabric.md) | DATA-10..14, 34, 43..45 | 9 |
| W4 | M2 | [Delta and releases](w4-delta-releases.md) | DATA-19..25, 37, 39, 51..60 | 19 |
| W5 | M3 | [Query and graph](w5-query-graph.md) | CORE-22..31; DATA-15..18, 46..50 | 19 |
| W6 | M3 | [Semantic change](w6-semantic-change.md) | DATA-26, 28, 38 | 3 |
| W7a | M4 | [Generator foundations](w7a-generator-foundations.md) | CORE-32..44; PROJ-01..07 | 20 |
| W7b | M4 | [Notation generators](w7b-notation-generators.md) | PROJ-08..34 | 27 |
| W8 | M5 | [Portal and export](w8-portal-export.md) | PROJ-35..41 | 7 |
| W9 | M6 | [Qualification](w9-qualification.md) | CORE-46, 67; DATA-40, 42; PROJ-42 | 5 |

Total 169: CORE-01..67, DATA-01..60, PROJ-01..42.

[W2/W3 execution handoff](w2-w3-handoff.md) records what W2 has landed on `wave-2/authoring`,
the uncommitted remainder of W2, and the full W3 work breakdown for the agent that continues.

## Dependency order

```text
W0 foundation
 -> W1 core schemas
     -> W2 authoring and semantic identity
         -> W3 Arrow fabric
             -> W4 Delta persistence and releases
                 -> W5 release-scoped query and graph
                     -> W6 semantic change and operations
                     -> W7a generator foundations
                         -> W7b notation generators
                             -> W8 portal and export
                                 -> W9 cross-family qualification
```

W7a depends on W5, not W6: view membership resolution needs the release-scoped query context, not
the change narrative.

## Four boundary decisions

Each resolves a dependency inversion in the naive reading of M1..M6.

**The semantic hash lands in W2, not with the change records.** DATA-21 requires the release
manifest to pin a semantic digest per table, and CORE-20, CORE-21 and DATA-45 all reference the
hash before any change record exists. One versioned implementation is delivered in W2; W3 extends
it to table level, W4 pins it, W6 builds the change narrative on it. The **hash primitive lives in
`domain/`** because it is the canonical normal form. Diff and classification were planned for
`releases/` and landed in `changes/`, a layer above it: W5 made `queries/` import `releases/`, so a
change record living in `releases/` could not carry the `TraversalResult` DATA-26 asks for without
a circular import.

**DATA-29..31 and DATA-41 land in W1.** Status dimensions, explicit behavior and ERD semantics, and
unknown or evidence-gap states are record fields. Added after W4 publishes immutable manifests they
would force a DATA-56 migration.

**W7 splits.** CORE-38 (no standards XML from Jinja), CORE-40 and CORE-41 (secure parser,
checksummed local resolver) and CORE-43 (C14N digests) are boundaries that must exist before the
first generator, not after it.

**The evidence substrate lands in W0 and W1.** CORE-49's requirement-evidence report is the
instrument every later gate is measured with. Left in M6, waves W1..W8 emit nothing
machine-readable.

The last three of these require amendments A1..A4 to `docs/agent-handoff.md`, recorded in
`reference/plan-waves.json` under `milestone_amendments`.

## Executing a wave

1. Read the wave document, its cited contract sections and the requirement statements it owns.
2. Implement in the single Python 3.14 uv project. Do not start a later wave's package.
3. Mark every test with `@pytest.mark.requirement("<ID>")` for the identifiers it evidences.
4. Run the wave's executable checks plus the full list in [agent handoff](../agent-handoff.md).
5. The PR names its requirement IDs, executable checks, remaining gaps and design questions.

A requirement listed under **Policy only** in a wave is satisfied by a documented constraint plus a
guard test. Reviewers should not expect a feature for it. Prefer a structural rule under `rules/`
over a hand-written pattern; see [contract enforcement](../contract-enforcement.md) for the tiers
and for why each guard must carry a known-bad case.

## Status

W0 and W1 are complete. Current executable evidence is recorded in
[qualification](../qualification.md). Scheduling a requirement here is not evidence that it is
satisfied, and neither is a wave being marked complete: read the wave document's own risks and
open questions, which record what each wave could not establish.

No wave has yet been verified on the Linux runner.
