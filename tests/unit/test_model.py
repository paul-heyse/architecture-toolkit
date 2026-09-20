"""The canonical model records (CORE-01, DATA-03, DATA-04, DATA-05, DATA-08, DATA-29, DATA-41)."""

import json
from typing import Any

import pytest

from architecture_toolkit.domain.details import BehaviorDetail, DataSchemaDetail
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.status import GapState
from architecture_toolkit.validation.pipeline import validate_model


@pytest.mark.unit
@pytest.mark.requirement("CORE-07", "DATA-03")
def test_reports_a_dangling_endpoint_as_a_diagnostic(
    minimal_model_source: dict[str, Any],
) -> None:
    """A behaviour change, and the point of CORE-07.

    This used to raise `ValidationError` from a validator on `Model`. Endpoint resolution is a
    cross-record question and §3F puts it outside record-local validators, so it is now a
    diagnostic — which can say which relationship and which side, where the exception could only
    say that something somewhere was wrong.
    """
    raw = minimal_model_source
    raw["relationships"][0]["target_element_id"] = "missing"
    model = Model.model_validate_json(json.dumps(raw))

    report = validate_model(model)
    unresolved = [d for d in report.diagnostics if d.code == "CORE.RELATION.UNRESOLVED_ENDPOINT"]
    assert len(unresolved) == 1
    assert unresolved[0].relationship_id == "rel-1"
    assert unresolved[0].field_path == "relationships.rel-1.target_element_id"
    assert report.hard_errors


@pytest.mark.unit
@pytest.mark.requirement("DATA-05", "DATA-29", "DATA-41")
def test_parallel_relations_and_manual_process_are_preserved(
    minimal_model_source: dict[str, Any],
) -> None:
    """Two distinct claims that happen to share a fixture.

    Parallel relationships keep their own identities — DATA-05 gives relationships their own IDs
    precisely so a second `contains` between the same pair is a second fact, not a duplicate to
    be collapsed. And nothing substitutes a value for the unknowns the fixture states.
    """
    raw = minimal_model_source
    baseline = len(raw["relationships"])
    raw["relationships"].append({**raw["relationships"][0], "relationship_id": "parallel"})
    model = Model.model_validate_json(json.dumps(raw))

    assert len(model.relationships) == baseline + 1
    assert model.relationships[0].source_element_id == model.relationships[-1].source_element_id
    assert model.relationships[0].relationship_id != model.relationships[-1].relationship_id

    by_id = {element.element_id: element for element in model.elements}
    assert by_id["process-1"].status.technical_qualification == "not_qualified"
    assert by_id["role-1"].status.client_acceptance is GapState.WITHHELD
    assert by_id["capability-1"].status.implementation_state is GapState.UNKNOWN


@pytest.mark.unit
@pytest.mark.requirement("DATA-08")
def test_a_handoff_answers_both_questions(minimal_model_source: dict[str, Any]) -> None:
    """DATA-08's two named queries, which a binary edge cannot serve."""
    model = Model.model_validate_json(json.dumps(minimal_model_source))
    handoff = model.interactions[0]

    participants = {p.element_id: p.participant_role for p in handoff.participants}
    assert set(participants) == {"process-1", "role-1", "interface-1"}

    moving_object_1 = [i for i in model.interactions if "object-1" in i.moved_object_ids]
    assert [i.interaction_id for i in moving_object_1] == ["handoff-1"]


@pytest.mark.unit
@pytest.mark.requirement("DATA-09")
def test_evidence_links_to_one_field_not_a_whole_application(
    minimal_model_source: dict[str, Any],
) -> None:
    """§2E: evidence supports a specific assertion, not everything about an element."""
    model = Model.model_validate_json(json.dumps(minimal_model_source))
    link = model.reference_links[0]
    assert link.subject.subject_kind == "field"
    assert link.subject.field_path == "detail.authentication_description"
    assert link.link_role == "supports"


@pytest.mark.unit
@pytest.mark.requirement("DATA-30")
def test_behaviour_is_modelled_explicitly_not_inferred(
    minimal_model_source: dict[str, Any],
) -> None:
    """DATA-30. No `supports` edge yields an exclusive gateway, so it is stated."""
    model = Model.model_validate_json(json.dumps(minimal_model_source))
    process = next(e for e in model.elements if e.element_id == "process-1")
    # Narrowing, not decoration: this asserts the discriminated union resolved to the variant the
    # tag named, which is the CORE-04 claim. Pyrefly rejects the attribute access without it.
    assert isinstance(process.detail, BehaviorDetail)
    node_types = {node.node_type for node in process.detail.nodes}
    assert "exclusive_gateway" in node_types
    assert "manual_task" in node_types
    guards = {t.guard for t in process.detail.transitions if t.guard}
    assert guards == {"amount > threshold", "otherwise"}


@pytest.mark.unit
@pytest.mark.requirement("DATA-30")
def test_erd_keys_are_stated_not_derived(minimal_model_source: dict[str, Any]) -> None:
    model = Model.model_validate_json(json.dumps(minimal_model_source))
    schema = next(e for e in model.elements if e.element_id == "schema-1")
    assert isinstance(schema.detail, DataSchemaDetail)
    by_name = {field.field_id: field for field in schema.detail.fields}
    assert "primary_key" in by_name["request_id"].key_membership
    assert "foreign_key" in by_name["submitted_by"].key_membership
    assert by_name["submitted_by"].references_element_id == "role-1"
    assert [field.ordinal for field in schema.detail.fields] == [0, 1, 2]


@pytest.mark.unit
@pytest.mark.requirement("DATA-04")
def test_identity_is_independent_of_display_name(minimal_model_source: dict[str, Any]) -> None:
    model = Model.model_validate_json(json.dumps(minimal_model_source))
    process = next(e for e in model.elements if e.element_id == "process-1")
    assert process.name == "Review request"
    assert process.aliases == ("Request review",)
