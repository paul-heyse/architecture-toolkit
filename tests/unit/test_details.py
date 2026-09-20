"""Typed detail families and the element-detail union (CORE-04, DATA-07, DATA-30)."""

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.details import (
    ELEMENT_DETAIL_ADAPTER,
    BehaviorDetail,
    DataSchemaDetail,
    ElementDetail,
)
from architecture_toolkit.domain.model import Element
from architecture_toolkit.domain.notation import NotationBinding
from architecture_toolkit.domain.registry import DetailFamily

ELEMENT_ATTACHABLE = frozenset(
    {
        DetailFamily.INTERFACE,
        DetailFamily.DEPLOYMENT,
        DetailFamily.DATA_SCHEMA,
        DetailFamily.BEHAVIOR,
        DetailFamily.REQUIREMENT,
    }
)


def union_variants() -> tuple[type, ...]:
    return get_args(get_args(ElementDetail)[0])


@pytest.mark.unit
@pytest.mark.requirement("DATA-07")
def test_six_families_of_which_five_attach_to_an_element() -> None:
    """DATA-07 names six details; only five can hang off an element.

    Notation bindings are the sixth. They are a separate record because their subject may be a
    relationship, they carry their own identity, and there may be many per subject — none of
    which an element-attached variant can express.
    """
    assert len(DetailFamily) == 6
    assert ELEMENT_ATTACHABLE | {DetailFamily.NOTATION_BINDING} == set(DetailFamily)
    assert len(union_variants()) == 5


@pytest.mark.unit
@pytest.mark.requirement("CORE-04")
def test_the_union_is_field_discriminated_all_the_way_into_json_schema() -> None:
    """CORE-13 asks for discriminators in the generated contract, not just at runtime."""
    schema = ELEMENT_DETAIL_ADAPTER.json_schema()
    discriminator = schema["discriminator"]
    assert discriminator["propertyName"] == "detail_family"
    assert set(discriminator["mapping"]) == {family.value for family in ELEMENT_ATTACHABLE}


@pytest.mark.unit
@pytest.mark.requirement("CORE-04")
def test_an_unknown_variant_tag_is_rejected_by_tag_not_by_shape() -> None:
    with pytest.raises(ValidationError) as caught:
        ELEMENT_DETAIL_ADAPTER.validate_json(
            json.dumps({"detail_family": "invented", "element_id": "x-1"})
        )
    assert {e["type"] for e in caught.value.errors(include_url=False)} == {"union_tag_invalid"}


@pytest.mark.unit
@pytest.mark.requirement("DATA-30")
def test_a_foreign_key_must_name_what_it_references() -> None:
    """Record-local, so Pydantic owns it. Whether the target exists is cross-record."""
    payload = {
        "detail_family": "data_schema",
        "element_id": "schema-1",
        "fields": [
            {
                "field_id": "f",
                "field_name": "f",
                "data_type": "string",
                "key_membership": ["foreign_key"],
                "ordinal": 0,
            }
        ],
    }
    with pytest.raises(ValidationError, match="names no referenced element"):
        DataSchemaDetail.model_validate_json(json.dumps(payload))


@pytest.mark.unit
@pytest.mark.requirement("DATA-30")
def test_a_behaviour_transition_cannot_leave_its_own_record() -> None:
    payload = {
        "detail_family": "behavior",
        "element_id": "process-1",
        "nodes": [{"node_id": "a", "node_type": "task", "name": "A", "ordinal": 0}],
        "transitions": [
            {"transition_id": "t", "source_node_id": "a", "target_node_id": "ghost", "ordinal": 0}
        ],
    }
    with pytest.raises(ValidationError, match="unknown nodes"):
        BehaviorDetail.model_validate_json(json.dumps(payload))


@pytest.mark.unit
@pytest.mark.requirement("DATA-30")
def test_the_three_bpmn_gateways_are_distinct_values() -> None:
    """The concrete reason DATA-30 exists: no edge label recovers exclusive from parallel."""
    from architecture_toolkit.domain.details import BehaviorNodeType

    gateways = {m.value for m in BehaviorNodeType if m.value.endswith("_gateway")}
    assert gateways == {"exclusive_gateway", "parallel_gateway", "inclusive_gateway"}


@pytest.mark.unit
@pytest.mark.requirement("CORE-04")
def test_a_detail_must_describe_the_element_it_hangs_on() -> None:
    payload = {
        "element_id": "interface-1",
        "model_id": "m-1",
        "kind_id": "software.interface",
        "name": "API",
        "detail": {
            "detail_family": "interface",
            "element_id": "someone-else",
            "transport": {
                "protocol": "https",
                "interaction_mode": "synchronous",
                "serialization": "json",
            },
        },
    }
    with pytest.raises(ValidationError, match="declares element_id"):
        Element.model_validate_json(json.dumps(payload))


@pytest.mark.unit
@pytest.mark.requirement("DATA-07", "DATA-31")
def test_a_notation_binding_can_address_a_relationship() -> None:
    """The property that rules out modelling it as an element detail."""
    binding = NotationBinding.model_validate_json(
        json.dumps(
            {
                "binding_id": "binding-2",
                "model_id": "m-1",
                "subject": {"subject_kind": "relationship", "relationship_id": "rel-1"},
                "notation": "archimate",
                "notation_type": "ArchiMate:Serving",
                "notation_object_id": "id-8f21",
                "mapping_profile_version": "1.0.0",
            }
        )
    )
    assert binding.subject.subject_kind == "relationship"
    # Presentation is absent by construction: no coordinates, bendpoints or geometry here.
    assert "layout" not in NotationBinding.model_fields
    assert not {f for f in NotationBinding.model_fields if "coordinate" in f or "bendpoint" in f}
