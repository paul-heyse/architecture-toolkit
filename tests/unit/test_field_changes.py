"""How far the differ descends, where it stops, and what it refuses (DATA-26).

Each case here is a ruling that could plausibly have gone the other way, so each one is written
against a value rather than against a shape: "it reported something" would pass for most of the
wrong answers too.
"""

from pathlib import Path

import pytest

from architecture_toolkit.changes.diff import (
    PRESENTATION_FIELDS,
    field_changes,
    model_changes,
    presentation_changes,
)
from architecture_toolkit.changes.errors import DiffError
from architecture_toolkit.changes.kinds import ChangeKind, ChangeNature
from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.details import DataSchemaDetail, InterfaceDetail
from architecture_toolkit.domain.model import Element, Model
from architecture_toolkit.domain.status import LifecycleState, TechnicalQualification

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "minimal" / "model.yaml"


@pytest.fixture
def model() -> Model:
    return parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))


def element(model: Model, element_id: str) -> Element:
    return next(item for item in model.elements if item.element_id == element_id)


def with_element(model: Model, element_id: str, **changes: object) -> Model:
    victim = element(model, element_id)
    replaced = victim.model_validate(dict(victim) | changes)
    return model.model_validate(
        dict(model)
        | {
            "elements": tuple(
                replaced if item.element_id == element_id else item for item in model.elements
            )
        }
    )


def paths(model: Model, candidate: Model) -> list[str]:
    return [
        change.identity_path
        for record in model_changes(model, candidate).records
        for change in record.fields
    ]


# -- how far it descends --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_a_nested_detail_change_lands_on_the_field_not_on_the_element(model: Model) -> None:
    """Reporting `elements.interface-1.detail` would be true and useless."""
    detail = element(model, "interface-1").detail
    assert isinstance(detail, InterfaceDetail)
    changed = with_element(
        model, "interface-1", detail=detail.model_validate(dict(detail) | {"timeout_ms": 5000})
    )

    assert paths(model, changed) == ["elements.interface-1.detail.timeout_ms"]


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_a_nested_value_object_is_descended_into(model: Model) -> None:
    """`InterfaceDetail.transport` is a record, so the change is about the protocol."""
    detail = element(model, "interface-1").detail
    assert isinstance(detail, InterfaceDetail)
    transport = detail.transport.model_validate(dict(detail.transport) | {"protocol": "grpc"})
    changed = with_element(
        model, "interface-1", detail=detail.model_validate(dict(detail) | {"transport": transport})
    )

    assert paths(model, changed) == ["elements.interface-1.detail.transport.protocol"]


@pytest.mark.unit
@pytest.mark.requirement("DATA-29")
def test_a_status_change_names_the_dimension_it_moved(model: Model) -> None:
    """One `status` path would re-collapse the five axes DATA-29 spent a module separating."""
    victim = element(model, "system-1")
    status = victim.status.model_validate(
        dict(victim.status) | {"technical_qualification": TechnicalQualification.QUALIFIED}
    )
    changed = with_element(model, "system-1", status=status)

    found = model_changes(model, changed).records[0].fields
    assert [change.identity_path for change in found] == [
        "elements.system-1.status.technical_qualification"
    ]
    assert found[0].kind is ChangeKind.QUALIFICATION_CHANGED


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_an_identity_keyed_nested_collection_is_paired_by_key_not_by_position(
    model: Model,
) -> None:
    """Reversing the ordinals moves two fields, not every field of every row."""
    detail = element(model, "schema-1").detail
    assert isinstance(detail, DataSchemaDetail)
    last = len(detail.fields) - 1
    reordered = detail.model_validate(
        dict(detail)
        | {
            "fields": tuple(
                item.model_validate(dict(item) | {"ordinal": last - item.ordinal})
                for item in detail.fields
            )
        }
    )
    changed = with_element(model, "schema-1", detail=reordered)

    found = paths(model, changed)
    assert found == [
        "elements.schema-1.detail.fields.note.ordinal",
        "elements.schema-1.detail.fields.request_id.ordinal",
    ]
    assert not any("[" in path for path in found), "a path must never carry a tuple index"


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_an_element_acquiring_a_detail_is_one_fact_not_ten(model: Model) -> None:
    """Descending a `None` would narrate a new contract as ten separate field changes."""
    stripped = with_element(model, "interface-1", detail=None)

    forward = model_changes(model, stripped).records[0]
    backward = model_changes(stripped, model).records[0]

    assert [change.field_path for change in forward.fields] == ["detail"]
    assert forward.kinds == (ChangeKind.DETAIL_REMOVED,)
    assert backward.kinds == (ChangeKind.DETAIL_ADDED,)


# -- what it reports, and how it classifies --------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_a_retirement_is_a_changed_record_and_never_a_removal(model: Model) -> None:
    """`RetireElement` leaves the element in place; a differ that said "removed" would lie."""
    retired = with_element(model, "capability-1", lifecycle_state=LifecycleState.RETIRED)

    changes = model_changes(model, retired)

    assert changes.kinds == {ChangeKind.ELEMENT_RETIRED}
    assert ChangeKind.ELEMENT_REMOVED not in changes.kinds
    assert ChangeKind.ELEMENT_ADDED not in changes.kinds
    assert changes.records[0].fields[0].identity_path == "elements.capability-1.lifecycle_state"


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_a_record_with_two_changed_fields_carries_both_kinds(model: Model) -> None:
    """No precedence. Picking a winner is how a rename starts hiding an endpoint change."""
    renamed = with_element(model, "capability-1", name="Renamed", description="Also this")

    record = model_changes(model, renamed).records[0]

    assert set(record.kinds) == {ChangeKind.ELEMENT_RENAMED, ChangeKind.FIELD_MODIFIED}
    assert len(record.fields) == 2


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_the_before_and_after_are_the_digests_own_spelling(model: Model) -> None:
    renamed = with_element(model, "capability-1", name="Renamed")

    change = model_changes(model, renamed).records[0].fields[0]

    assert change.before == '"Handle customer requests"'
    assert change.after == '"Renamed"'


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_an_element_change_can_be_addressed_with_the_existing_reference_type(
    model: Model,
) -> None:
    """`FieldReference` is how evidence already addresses a field; a diff should join to it."""
    renamed = with_element(model, "capability-1", name="Renamed")

    change = model_changes(model, renamed).records[0].fields[0]
    reference = change.as_field_reference()

    assert reference is not None
    assert reference.element_id == "capability-1"
    assert reference.field_path == "name"


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_a_collection_without_a_field_granular_address_says_so_rather_than_inventing_one(
    model: Model,
) -> None:
    first = model.relationships[0]
    described = model.model_validate(
        dict(model)
        | {
            "relationships": (
                first.model_validate(dict(first) | {"description": "now explained"}),
                *model.relationships[1:],
            )
        }
    )

    change = model_changes(model, described).records[0].fields[0]

    assert change.collection == "relationships"
    assert change.as_field_reference() is None


# -- the presentation pass -------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-04", "DATA-26")
def test_the_presentation_pass_is_derived_from_the_hash_policy(model: Model) -> None:
    """Hand-writing this set would be a second source of truth for what the digest excludes."""
    assert PRESENTATION_FIELDS == {(Element, "aliases")}


@pytest.mark.unit
@pytest.mark.requirement("DATA-04", "DATA-26")
def test_an_alias_edit_is_invisible_to_the_field_diff_and_visible_to_the_presentation_pass(
    model: Model,
) -> None:
    victim = element(model, "capability-1")
    relabelled = victim.model_validate(dict(victim) | {"aliases": ("Portfolio Eval",)})

    assert field_changes("elements", "capability-1", victim, relabelled) == ()
    reported = presentation_changes("elements", "capability-1", victim, relabelled)
    assert [change.field_path for change in reported] == ["aliases"]
    assert reported[0].kind is ChangeKind.DISPLAY_NAME_CHANGED
    assert reported[0].nature is ChangeNature.LAYOUT_ONLY


# -- refusals -------------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_two_different_record_types_are_refused_rather_than_compared(model: Model) -> None:
    with pytest.raises(DiffError, match="cannot diff"):
        field_changes("elements", "x", model.elements[0], model.relationships[0])


@pytest.mark.unit
@pytest.mark.requirement("DATA-28")
def test_two_different_models_are_not_a_diff(model: Model) -> None:
    """A scenario against its baseline is an alternative comparison, not a revision."""
    other = model.model_validate(dict(model) | {"model_id": "other-model"})

    with pytest.raises(DiffError, match="different models"):
        model_changes(model, other)


@pytest.mark.unit
@pytest.mark.requirement("DATA-26")
def test_a_field_declared_unable_to_differ_raises_rather_than_being_reported(
    model: Model,
) -> None:
    """Enforcing `NEVER_EMITTED` instead of asserting it.

    `model_id` is a match-key-adjacent field on every child record; two versions of one element
    cannot disagree about it. Constructing the impossible case proves the guard fires.
    """
    victim = element(model, "capability-1")
    impostor = victim.model_validate(dict(victim) | {"model_id": "another-model"})

    with pytest.raises(DiffError, match="record_identity"):
        field_changes("elements", "capability-1", victim, impostor)
