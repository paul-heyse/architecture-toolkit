"""Five independent dimensions and explicit gap states (DATA-29, DATA-41)."""

import json
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.status import (
    STATUS_DIMENSIONS,
    EvidenceReview,
    GapState,
    LifecycleState,
    StatusDimensions,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
@pytest.mark.requirement("DATA-29")
def test_there_are_exactly_five_independent_dimensions() -> None:
    assert len(StatusDimensions.model_fields) == 5
    assert len(STATUS_DIMENSIONS) == 5


@pytest.mark.unit
@pytest.mark.requirement("DATA-29", "DATA-41")
@pytest.mark.parametrize("dimension", STATUS_DIMENSIONS, ids=lambda d: d.__name__)
def test_dimension_vocabularies_are_disjoint_from_the_gap_states(dimension: type[StrEnum]) -> None:
    """A dimension that defined its own `unknown` would shadow `GapState.UNKNOWN`.

    The field is typed `Dimension | GapState`, and Pydantic resolves a JSON string against the
    left member first. A collision would silently change which type a value parses into, so the
    two vocabularies must never overlap.
    """
    overlap = {member.value for member in dimension} & {member.value for member in GapState}
    assert not overlap, f"{dimension.__name__} shadows gap state(s) {sorted(overlap)}"


@pytest.mark.unit
@pytest.mark.requirement("DATA-29")
def test_lifecycle_state_is_not_a_status_dimension() -> None:
    """Notion carries both and never relates them; W1's call is that they are different axes.

    `lifecycle_state` is whether the record is live. The five dimensions assess a live record.
    Encoding retirement in both places would let them disagree, so their value sets stay
    disjoint and lifecycle is not a member of `StatusDimensions`.
    """
    assert "lifecycle_state" not in StatusDimensions.model_fields
    lifecycle = {member.value for member in LifecycleState}
    for dimension in STATUS_DIMENSIONS:
        assert not lifecycle & {member.value for member in dimension}


@pytest.mark.unit
@pytest.mark.requirement("DATA-41")
@pytest.mark.parametrize("gap", list(GapState), ids=lambda g: g.value)
@pytest.mark.parametrize("field", list(StatusDimensions.model_fields))
def test_every_dimension_can_express_every_gap(field: str, gap: GapState) -> None:
    """DATA-41: unknown, not-applicable, withheld and evidence-gap stay expressible everywhere.

    Through JSON, because that is the authoring path: strict Python mode requires an actual enum
    member, while strict JSON mode resolves the string against the union.
    """
    record = StatusDimensions.model_validate_json(json.dumps({field: gap.value}))
    assert getattr(record, field) is gap


@pytest.mark.unit
@pytest.mark.requirement("DATA-41")
def test_unasserted_defaults_are_explicit_unknowns() -> None:
    """A default must not invent a fact.

    `technical_qualification`, `client_acceptance` and `evidence_review` have genuine zero states:
    nothing has been qualified, requested or reviewed. `design_disposition` and
    `implementation_state` do not — defaulting them to `proposed` and `not_implemented` would
    assert an intent nobody expressed and deny the existence of systems documented from
    observation.
    """
    fresh = StatusDimensions()
    assert fresh.design_disposition is GapState.UNKNOWN
    assert fresh.implementation_state is GapState.UNKNOWN
    assert fresh.technical_qualification.value == "not_qualified"
    assert fresh.client_acceptance.value == "not_requested"
    assert fresh.evidence_review.value == "unreviewed"


@pytest.mark.unit
@pytest.mark.requirement("DATA-29")
def test_an_invented_value_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        StatusDimensions.model_validate_json(json.dumps({"design_disposition": "invented"}))
    assert {error["type"] for error in caught.value.errors(include_url=False)} == {"enum"}


@pytest.mark.unit
@pytest.mark.requirement("DATA-29")
def test_dimensions_are_not_a_progression() -> None:
    """Implemented-but-not-qualified and accepted-before-implemented are both legal.

    `ARCH-TOOL-DATA-001` §6C: "neither is a contradictory state". Any model that ordered these
    would have to reject one of them.
    """
    implemented_unqualified = StatusDimensions.model_validate_json(
        json.dumps(
            {"implementation_state": "implemented", "technical_qualification": "not_qualified"}
        )
    )
    accepted_unbuilt = StatusDimensions.model_validate_json(
        json.dumps({"client_acceptance": "accepted", "implementation_state": "not_implemented"})
    )
    assert implemented_unqualified.implementation_state.value == "implemented"
    assert accepted_unbuilt.client_acceptance.value == "accepted"


# The single `design_state` axis from the overview record, which the detailed proposal supersedes
# by splitting it into five independent dimensions. Reproduced verbatim so the decomposition is
# checkable: if a dimension drops a term, or two dimensions both claim one, this fails.
SUPERSEDED_DESIGN_STATE = (
    "candidate",
    "proposed",
    "analytically_feasible",
    "runtime_qualified",
    "client_accepted",
    "implemented",
)

# The `evidence_state` axis from the same record, which maps to one dimension rather than being
# split.
SUPERSEDED_EVIDENCE_STATE = (
    "observed",
    "client_stated",
    "public_research",
    "inferred",
    "assumption",
)


# Where each superseded term lands. Written out rather than inferred, because two dimensions can
# legitimately share a word: `accepted` means "the design was accepted" under `DesignDisposition`
# and "the client accepted it" under `ClientAcceptance`, which are precisely the two facts DATA-29
# insists are separate. They are unambiguous because each is reached through its own field — the
# ambiguity that *does* matter is with `GapState`, since those share a field through a union, and
# that is checked separately above.
DECOMPOSITION: dict[str, tuple[str, str]] = {
    "candidate": ("DesignDisposition", "candidate"),
    "proposed": ("DesignDisposition", "proposed"),
    "analytically_feasible": ("DesignDisposition", "analytically_feasible"),
    "implemented": ("ImplementationState", "implemented"),
    "runtime_qualified": ("TechnicalQualification", "qualified"),
    "client_accepted": ("ClientAcceptance", "accepted"),
}


@pytest.mark.unit
@pytest.mark.requirement("DATA-29")
def test_the_decomposition_covers_the_whole_superseded_axis() -> None:
    assert set(DECOMPOSITION) == set(SUPERSEDED_DESIGN_STATE)


@pytest.mark.unit
@pytest.mark.requirement("DATA-29")
@pytest.mark.parametrize("term", SUPERSEDED_DESIGN_STATE)
def test_every_superseded_design_state_term_has_a_home(term: str) -> None:
    """DATA-29 is a decomposition, so nothing in the thing decomposed may be lost.

    Two terms read differently once split: `runtime_qualified` becomes `qualified` under
    `TechnicalQualification` and `client_accepted` becomes `accepted` under `ClientAcceptance`.
    Both are better for it — the dimension already carries the qualifier the old name had to
    spell out, which is what made the single axis unwieldy in the first place.
    """
    dimension_name, value = DECOMPOSITION[term]
    dimension = next(d for d in STATUS_DIMENSIONS if d.__name__ == dimension_name)
    assert value in {member.value for member in dimension}


@pytest.mark.unit
@pytest.mark.requirement("DATA-29")
def test_the_evidence_vocabulary_matches_its_source() -> None:
    """The one dimension with a directly sourced list. `unreviewed` is the added zero state."""
    values = {member.value for member in EvidenceReview}
    assert set(SUPERSEDED_EVIDENCE_STATE) <= values
    assert values - set(SUPERSEDED_EVIDENCE_STATE) == {"unreviewed"}


@pytest.mark.unit
@pytest.mark.requirement("DATA-41")
def test_the_gap_states_reproduce_global_invariant_eleven() -> None:
    """`docs/implementation-contract.md`: "Unknown/not-applicable/withheld/evidence-gap states
    remain explicit." Four named states, and these are those four.

    Read from the contract rather than hardcoded, so editing the invariant without editing the
    enum fails here.
    """
    invariant = next(
        line
        for line in (ROOT / "docs" / "implementation-contract.md").read_text().splitlines()
        if "states remain explicit" in line
    )
    lowered = invariant.lower()
    for member in GapState:
        assert member.value.replace("_", "-") in lowered, member.value
    assert len(GapState) == invariant.count("/") + 1
