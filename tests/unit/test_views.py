"""Canonical view definitions (PROJ-03).

Not yet reachable from `Model` — that arrives with the `views` collection. What is asserted here
is the record's own contract: the vocabularies it closes, and the three questions one record can
answer about itself.
"""

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.notation import Notation
from architecture_toolkit.domain.views import (
    VIEW_TYPES_BY_NOTATION,
    FilterDimension,
    FilterMode,
    MembershipPolicy,
    PublicationState,
    ViewDefinition,
    ViewFilter,
    ViewType,
)


def view(**overrides: object) -> ViewDefinition:
    payload: dict[str, object] = {
        "view_id": "view-1",
        "model_id": "m-1",
        "view_type": ViewType.SYSTEM_CONTEXT,
        "notation": Notation.C4,
        "title": "Context",
    }
    return ViewDefinition.model_validate(payload | overrides)


@pytest.mark.unit
@pytest.mark.requirement("PROJ-03")
def test_every_notation_and_every_view_type_is_accounted_for() -> None:
    """Total in both directions, so a new notation or view type forces a decision.

    Without the second assertion a view type could be declared and belong to no notation, which
    would make it unconstructible while looking available.
    """
    assert set(VIEW_TYPES_BY_NOTATION) == set(Notation)
    assert {t for types in VIEW_TYPES_BY_NOTATION.values() for t in types} == set(ViewType)


@pytest.mark.unit
@pytest.mark.requirement("PROJ-03", "PROJ-08")
def test_a_code_level_c4_view_cannot_be_named_at_all() -> None:
    """PROJ-08 excludes code diagrams. A closed vocabulary makes that inexpressible."""
    assert "code" not in {member.value for member in ViewType}


@pytest.mark.unit
@pytest.mark.requirement("PROJ-03")
def test_a_view_type_its_notation_cannot_express_is_refused() -> None:
    with pytest.raises(ValidationError, match="expresses"):
        view(notation=Notation.C4, view_type=ViewType.BPMN_PROCESS)
    assert view(notation=Notation.BPMN, view_type=ViewType.BPMN_PROCESS).notation is Notation.BPMN


@pytest.mark.unit
@pytest.mark.requirement("PROJ-03")
def test_a_view_cannot_name_the_same_member_twice() -> None:
    with pytest.raises(ValidationError, match="more than once"):
        view(included_element_ids=("a-1", "a-1"))
    with pytest.raises(ValidationError, match="more than once"):
        view(included_relationship_ids=("rel-1", "rel-1"))
    assert view(included_element_ids=("a-1", "b-1")).member_count == 2


@pytest.mark.unit
@pytest.mark.requirement("PROJ-03")
def test_a_membership_policy_and_a_filter_have_to_agree() -> None:
    """Both directions, because either mismatch makes the membership uninterpretable."""
    rule = ViewFilter(
        filter_mode=FilterMode.INCLUDE, dimension=FilterDimension.KIND, values=("software.system",)
    )
    with pytest.raises(ValidationError, match="derive it from"):
        view(membership_policy=MembershipPolicy.DERIVED)
    with pytest.raises(ValidationError, match="explicit and declares a filter"):
        view(membership_policy=MembershipPolicy.EXPLICIT, filter=(rule,))
    assert view(membership_policy=MembershipPolicy.DERIVED, filter=(rule,)).filter == (rule,)
    assert view(membership_policy=MembershipPolicy.INDUCED, filter=(rule,)).filter == (rule,)


@pytest.mark.unit
@pytest.mark.requirement("PROJ-03")
def test_a_filter_names_at_least_one_value() -> None:
    """An empty value list selects nothing and excludes nothing: it is a filter that is not one."""
    with pytest.raises(ValidationError):
        ViewFilter(filter_mode=FilterMode.INCLUDE, dimension=FilterDimension.KIND, values=())


@pytest.mark.unit
@pytest.mark.requirement("PROJ-03", "DATA-41")
def test_the_optional_fields_are_facts_rather_than_gaps() -> None:
    """A landscape view has no scope and an auto-laid-out view has no profile."""
    landscape = view(view_type=ViewType.SYSTEM_LANDSCAPE)
    assert landscape.scope is None
    assert landscape.layout_profile_id is None
    assert landscape.publication_state is PublicationState.DRAFT
    assert not landscape.is_published


@pytest.mark.unit
@pytest.mark.requirement("PROJ-03", "CORE-08")
def test_a_view_is_frozen_and_hashable_like_every_other_published_record() -> None:
    first = view(included_element_ids=("a-1",))
    assert hash(first) == hash(view(included_element_ids=("a-1",)))
    with pytest.raises(ValidationError):
        first.title = "Renamed"  # pyrefly: ignore[read-only]
