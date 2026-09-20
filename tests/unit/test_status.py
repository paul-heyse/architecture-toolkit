"""Five independent dimensions and explicit gap states (DATA-29, DATA-41)."""

import json
from enum import StrEnum

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.status import (
    STATUS_DIMENSIONS,
    GapState,
    LifecycleState,
    StatusDimensions,
)


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
