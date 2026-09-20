"""Five independent status dimensions and the explicit gap states (DATA-29, DATA-41).

DATA-29 requires design disposition, implementation state, technical qualification, client
acceptance and evidence/review state to stay separate. They are five dimensions, never one linear
progression: `ARCH-TOOL-DATA-001` §6C puts it as "a design can be implemented but not qualified,
or client-approved before implementation. Neither is a contradictory state." Any model that
collapses them has to pick one of those to misrepresent.

**Unknown is a value, not a missing field.** DATA-41 requires unknowns, manual processes and
evidence gaps to be *preserved* rather than filled in to satisfy a structural check. A nullable
field says "nobody wrote anything here", which is indistinguishable from an oversight. A
`GapState` member says "we looked, and this is what we found" — which is the fact the requirement
wants recorded. So every dimension is `Dimension | GapState` and required, not `Dimension | None`.

`ARCH-TOOL-DATA-001` §10F is the test to hold this against: missing owner information is not an
invalid foreign key, and a manual process does not need an application simply to complete a
coverage matrix.

**The vocabularies are traceable to the accepted design, not invented here.** Two sources:

* `GapState` reproduces global invariant 11 of `docs/implementation-contract.md` exactly —
  "Unknown/not-applicable/withheld/evidence-gap states remain explicit." Four states, same four.
* `EvidenceReview` reproduces the `evidence_state` list from the overview record, plus
  `UNREVIEWED` as the zero state that list has no term for.

The other four dimensions decompose the overview record's single `design_state` axis, which the
detailed proposal supersedes precisely because one axis cannot hold five independent facts.
Every term in that superseded list lands in exactly one dimension here, and
`tests/unit/test_status.py` asserts that rather than leaving it to a reader to check:

| superseded `design_state` term | dimension it belongs to |
| --- | --- |
| `candidate`, `proposed`, `analytically_feasible` | `DesignDisposition` |
| `implemented` | `ImplementationState` |
| `runtime_qualified` | `TechnicalQualification` |
| `client_accepted` | `ClientAcceptance` |

That decomposition is the whole content of DATA-29. The remaining members — rejection,
supersession, partial implementation, failed qualification — exist because a dimension that can
only move forwards cannot express the states §6C says are not contradictory.

A profile may extend or replace any of these; see `registry.py`. They become durable when W4
pins them into immutable Delta manifests, so a change is cheap until then and a migration after.
"""

from enum import StrEnum

from architecture_toolkit.domain.base import CompiledRecord

__all__ = [
    "STATUS_DIMENSIONS",
    "ClientAcceptance",
    "DesignDisposition",
    "EvidenceReview",
    "GapState",
    "ImplementationState",
    "LifecycleState",
    "StatusDimensions",
    "TechnicalQualification",
]


class GapState(StrEnum):
    """Why a dimension has no ordinary value (DATA-41).

    Shared across all five dimensions, and asserted disjoint from each of them by
    `tests/unit/test_status.py` — a future vocabulary that added its own `unknown` would shadow
    this one and silently change what the union resolves to.
    """

    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    WITHHELD = "withheld"
    EVIDENCE_GAP = "evidence_gap"


class DesignDisposition(StrEnum):
    """Where the architectural decision stands. Not a claim about reality.

    `CANDIDATE` and `PROPOSED` are distinct because the source list distinguishes them and the
    difference is load-bearing for option analysis: a candidate is one of several options under
    consideration, a proposal is the one put forward. Collapsing them would make a toolkit that
    compares alternatives unable to say which alternative it is recommending.
    """

    CANDIDATE = "candidate"
    PROPOSED = "proposed"
    ANALYTICALLY_FEASIBLE = "analytically_feasible"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ImplementationState(StrEnum):
    """Whether the thing exists. Independent of whether anyone approved it."""

    NOT_IMPLEMENTED = "not_implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    IMPLEMENTED = "implemented"
    # Not "retired": that word belongs to `LifecycleState`, and the disjointness guard caught the
    # collision. The two are genuinely different facts — a system can be decommissioned while its
    # element stays in the model as history, and an element can be retired from the model while
    # the system it described keeps running — so they need different words, not a shared one.
    DECOMMISSIONED = "decommissioned"


class TechnicalQualification(StrEnum):
    """Whether it was tested. `NOT_QUALIFIED` is not a failure.

    The same distinction `domain/engineering.py` draws for tool evidence: a capability nobody has
    qualified yet and a capability that failed qualification are different facts, and merging them
    turns an unexplored option into a rejected one.
    """

    NOT_QUALIFIED = "not_qualified"
    QUALIFIED = "qualified"
    QUALIFICATION_FAILED = "qualification_failed"


class ClientAcceptance(StrEnum):
    """Whether the consumer has agreed. Orthogonal to whether it works."""

    NOT_REQUESTED = "not_requested"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EvidenceReview(StrEnum):
    """How the assertion is known — the one vocabulary with a source.

    Ordered from strongest to weakest grounding, though the enum imposes no ordering: an inferred
    fact and an observed one are both usable, and the difference is exactly what a reviewer needs
    to see.
    """

    UNREVIEWED = "unreviewed"
    OBSERVED = "observed"
    CLIENT_STATED = "client_stated"
    PUBLIC_RESEARCH = "public_research"
    INFERRED = "inferred"
    ASSUMPTION = "assumption"


class LifecycleState(StrEnum):
    """Whether the record itself is live. Distinct from every dimension above.

    Notion's elements table carries `lifecycle_state` and §6C carries the five dimensions, and
    neither says how they relate. The call taken in W1: this is the record's *existence* and is
    what `RetireElement` drives, while the five dimensions are *assessments of a live record*. A
    retired element keeps its last assessment rather than having it erased, because "this was
    accepted and then retired" is a different history from "this was never accepted".
    """

    ACTIVE = "active"
    RETIRED = "retired"
    # Not "superseded": `DesignDisposition` owns that word for a decision replaced by a later
    # decision. Here the *record* has a successor, which is a different fact about a different
    # thing, and the disjointness guard requires the two be sayable apart.
    REPLACED = "replaced"


# The five dimension enums, in the order DATA-29 names them. `tests/unit/test_status.py` iterates
# this to assert disjointness, so a sixth dimension added without a gap check fails there.
STATUS_DIMENSIONS: tuple[type[StrEnum], ...] = (
    DesignDisposition,
    ImplementationState,
    TechnicalQualification,
    ClientAcceptance,
    EvidenceReview,
)


class StatusDimensions(CompiledRecord):
    """Five independent assessments, each either a vocabulary value or an explicit gap.

    The defaults split on a principle worth stating, because getting it wrong is how a model
    starts asserting things nobody said. A dimension whose zero state is a genuine *fact* about a
    new record keeps that zero state: nothing has been qualified, nothing has been requested of a
    client, nothing has been reviewed. A dimension whose zero state would be a *claim* defaults to
    `UNKNOWN` instead:

    * `design_disposition` — authoring an element is not the same as proposing it. A model
      frequently documents what already exists, and defaulting to `PROPOSED` would invent an
      intent.
    * `implementation_state` — defaulting to `NOT_IMPLEMENTED` asserts the thing does not exist,
      which is false for every system documented from observation.

    DATA-41 is explicit that a value must never be invented to satisfy a structural rule, and a
    default is the easiest place for exactly that to happen unnoticed.
    """

    design_disposition: DesignDisposition | GapState = GapState.UNKNOWN
    implementation_state: ImplementationState | GapState = GapState.UNKNOWN
    technical_qualification: TechnicalQualification | GapState = (
        TechnicalQualification.NOT_QUALIFIED
    )
    client_acceptance: ClientAcceptance | GapState = ClientAcceptance.NOT_REQUESTED
    evidence_review: EvidenceReview | GapState = EvidenceReview.UNREVIEWED
