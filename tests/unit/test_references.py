"""References, evidence links and the canonical-object address (DATA-09, CORE-04)."""

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.references import (
    REFERENCE_TARGET_ADAPTER,
    FieldReference,
    LinkRole,
    Reference,
    ReferenceTarget,
    SubjectKind,
)


@pytest.mark.unit
@pytest.mark.requirement("DATA-09", "CORE-04")
def test_a_subject_is_one_of_the_four_kinds_data_09_names() -> None:
    variants = get_args(get_args(ReferenceTarget)[0])
    assert len(variants) == 4
    mapping = REFERENCE_TARGET_ADAPTER.json_schema()["discriminator"]["mapping"]
    assert set(mapping) == {kind.value for kind in SubjectKind}


@pytest.mark.unit
@pytest.mark.requirement("DATA-09")
def test_only_a_field_reference_carries_a_field_path() -> None:
    """The union earns its keep here: a field path is meaningless on the other three.

    A flat `(subject_kind, subject_id, field_path)` triple would let an element reference carry
    one, which is the imprecision §2E objects to.
    """
    assert "field_path" in FieldReference.model_fields
    for variant in get_args(get_args(ReferenceTarget)[0]):
        if variant is not FieldReference:
            assert "field_path" not in variant.model_fields, variant.__name__


@pytest.mark.unit
@pytest.mark.requirement("DATA-09")
def test_the_four_link_roles_include_disagreement() -> None:
    """`contradicts` is evidence, not an error state, and DATA-41 requires it be preserved."""
    assert {role.value for role in LinkRole} == {
        "supports",
        "contradicts",
        "justifies",
        "qualifies",
    }


@pytest.mark.unit
@pytest.mark.requirement("DATA-09")
def test_a_field_reference_needs_a_non_empty_path() -> None:
    with pytest.raises(ValidationError):
        REFERENCE_TARGET_ADAPTER.validate_json(
            json.dumps({"subject_kind": "field", "element_id": "interface-1", "field_path": ""})
        )


@pytest.mark.unit
@pytest.mark.requirement("DATA-09", "DATA-41")
def test_a_reference_without_a_locator_is_valid() -> None:
    """An interview has no URL. Inventing one to satisfy a structural rule is what DATA-41 bans."""
    reference = Reference.model_validate_json(
        json.dumps(
            {
                "reference_id": "ref-2",
                "model_id": "m-1",
                "reference_kind": "interview",
                "title": "Conversation with the platform team (synthetic)",
            }
        )
    )
    assert reference.locator is None
    assert reference.authority is None


@pytest.mark.unit
@pytest.mark.requirement("DATA-09")
def test_the_toolkit_stores_pointers_not_documents() -> None:
    """DATA-09's boundary: this is not a second evidence-extraction platform."""
    forbidden = {"content", "body", "text", "extracted_text", "attachment", "blob"}
    assert not forbidden & set(Reference.model_fields)
