"""Round-trip source editing driven by typed commands (CORE-20)."""

from pathlib import Path

import pytest

from architecture_toolkit.domain.authoring import (
    SourceEditError,
    SourceEditResult,
    apply_change_set_to_source,
    parse_model,
    parse_source,
)
from architecture_toolkit.domain.commands import (
    AddElement,
    AddRelationship,
    ChangeCommand,
    ChangeSet,
    RemoveRelationship,
    RenameElement,
    RetireElement,
    UpdateDetail,
    UpdateElement,
    build_candidate,
)
from architecture_toolkit.domain.details import InteractionMode, InterfaceDetail, InterfaceTransport
from architecture_toolkit.domain.model import Element, Relationship
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.validation.authoring import edit_and_validate

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
MODEL_ID = "sample-service"

COMMENTED = """\
model_id: demo
elements:
  - {element_id: sys-a, model_id: demo, kind_id: software.system, name: A}
  - {element_id: comp-b, model_id: demo, kind_id: software.component, name: B}
relationships:
  # above first
  - {relationship_id: rel-1, model_id: demo, relationship_type_id: contains,
     source_element_id: sys-a, target_element_id: comp-b}   # eol first
  # above second
  - {relationship_id: rel-2, model_id: demo, relationship_type_id: depends_on,
     source_element_id: comp-b, target_element_id: sys-a}   # eol second
  # above third
  - {relationship_id: rel-3, model_id: demo, relationship_type_id: supports,
     source_element_id: sys-a, target_element_id: comp-b}
"""


def _apply(
    text: str, *commands: ChangeCommand, expected: str | None = None
) -> tuple[ChangeSet, SourceEditResult]:
    change_set = ChangeSet(
        change_set_id="cs-1",
        model_id=parse_model(parse_source(text, source_id="t")).model_id,
        expected_base_digest=expected,
        commands=tuple(commands),
    )
    return change_set, apply_change_set_to_source(text, change_set, source_id="t")


def _equivalent(text: str, change_set: ChangeSet, edited_text: str) -> None:
    """The CORE-20 statement: editing the source equals applying the commands to the model."""
    baseline = parse_model(parse_source(text, source_id="t"))
    reparsed = parse_model(parse_source(edited_text, source_id="t"))
    assert model_digest(reparsed) == model_digest(build_candidate(baseline, change_set))


# -- one test per command variant, on the example -------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
def test_rename_edits_one_scalar_and_keeps_every_comment() -> None:
    text = EXAMPLE.read_text()
    change_set, result = _apply(
        text,
        RenameElement(element_id="process-1", new_name="Assess", expected_name="Review request"),
    )
    _equivalent(text, change_set, result.text)
    assert result.text.count("#") == text.count("#")
    assert "    name: Assess\n" in result.text
    assert [c.changed for c in result.delta.collections if c.collection == "elements"] == [
        ("process-1",)
    ]


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
def test_rename_with_a_stale_expected_name_is_refused() -> None:
    with pytest.raises(SourceEditError, match="is named"):
        _apply(
            EXAMPLE.read_text(),
            RenameElement(element_id="process-1", new_name="X", expected_name="Something else"),
        )


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
def test_retire_sets_the_lifecycle_state_exactly_as_the_command_engine_does() -> None:
    text = EXAMPLE.read_text()
    change_set, result = _apply(text, RetireElement(element_id="role-1", reason="not needed"))
    _equivalent(text, change_set, result.text)
    assert "lifecycle_state: retired" in result.text
    assert "not needed" not in result.text, "the reason is not model content"


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
def test_update_element_writes_descriptive_fields_in_place() -> None:
    text = EXAMPLE.read_text()
    change_set, result = _apply(
        text,
        UpdateElement(element_id="system-1", description="Described", aliases=("Req svc", "RS")),
    )
    _equivalent(text, change_set, result.text)
    assert "    description: Described\n" in result.text
    assert "    aliases: [Req svc, RS]\n" in result.text


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
def test_add_relationship_matches_the_surrounding_flow_style() -> None:
    text = EXAMPLE.read_text()
    added = Relationship(
        relationship_id="rel-9",
        model_id=MODEL_ID,
        relationship_type_id="supports",
        source_element_id="component-1",
        target_element_id="capability-1",
    )
    change_set, result = _apply(text, AddRelationship(relationship=added))
    _equivalent(text, change_set, result.text)
    assert "  - {relationship_id: rel-9, model_id: sample-service" in result.text


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
def test_add_element_renders_a_block_record_with_its_discriminator() -> None:
    text = EXAMPLE.read_text()
    element = Element(
        element_id="api-2",
        model_id=MODEL_ID,
        kind_id="software.interface",
        name="Second API",
        detail=InterfaceDetail(
            element_id="api-2",
            transport=InterfaceTransport(
                protocol="https", interaction_mode=InteractionMode.SYNCHRONOUS, serialization="json"
            ),
        ),
    )
    change_set, result = _apply(text, AddElement(element=element))
    _equivalent(text, change_set, result.text)
    assert "  - element_id: api-2\n" in result.text
    assert "      detail_family: interface\n" in result.text
    assert "content_hash" not in result.text


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
def test_update_detail_merges_a_same_family_detail_and_can_remove_one() -> None:
    text = EXAMPLE.read_text()
    replacement = InterfaceDetail(
        element_id="interface-1",
        transport=InterfaceTransport(
            protocol="grpc", interaction_mode=InteractionMode.ASYNCHRONOUS, serialization="protobuf"
        ),
        timeout_ms=5,
    )
    change_set, result = _apply(
        text,
        UpdateDetail(element_id="interface-1", detail=replacement),
        UpdateDetail(element_id="deployment-1", detail=None),
    )
    _equivalent(text, change_set, result.text)
    assert "protocol: grpc" in result.text
    assert "authentication_description: Bearer" not in result.text
    assert "environment: production" not in result.text


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
def test_a_stale_expected_base_digest_is_refused_before_any_edit() -> None:
    with pytest.raises(SourceEditError, match="not the expected"):
        _apply(
            EXAMPLE.read_text(),
            RenameElement(element_id="process-1", new_name="X"),
            expected="sha256:" + "0" * 64,
        )


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
def test_a_missing_record_is_refused_with_the_command_engines_wording() -> None:
    with pytest.raises(SourceEditError, match="does not exist"):
        _apply(EXAMPLE.read_text(), RenameElement(element_id="ghost-1", new_name="X"))


# -- comment preservation on removal ------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
@pytest.mark.parametrize("removed", ["rel-1", "rel-2", "rel-3"])
def test_removing_an_item_loses_only_its_own_end_of_line_comment(removed: str) -> None:
    change_set, result = _apply(COMMENTED, RemoveRelationship(relationship_id=removed))
    _equivalent(COMMENTED, change_set, result.text)
    own_eol = {"rel-1": "# eol first", "rel-2": "# eol second", "rel-3": None}[removed]
    for line in COMMENTED.splitlines():
        comment = line[line.index("#") :] if "#" in line else None
        if comment is None or comment == own_eol:
            continue
        assert comment in result.text, f"{comment!r} lost when removing {removed}"
    if own_eol is not None:
        assert own_eol not in result.text


@pytest.mark.unit
@pytest.mark.requirement("CORE-20")
def test_the_header_of_the_next_item_stays_above_it_after_a_removal() -> None:
    _, result = _apply(COMMENTED, RemoveRelationship(relationship_id="rel-2"))
    lines = result.text.splitlines()
    third = next(i for i, line in enumerate(lines) if "relationship_id: rel-3" in line)
    assert lines[third - 1].strip() == "# above third"


# -- the composed path --------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-19", "CORE-20")
def test_a_diagnostic_caused_by_an_edit_is_located_in_the_new_text() -> None:
    text = EXAMPLE.read_text()
    dangling = Relationship(
        relationship_id="rel-9",
        model_id=MODEL_ID,
        relationship_type_id="supports",
        source_element_id="component-1",
        target_element_id="nowhere-1",
    )
    change_set = ChangeSet(
        change_set_id="cs-2", model_id=MODEL_ID, commands=(AddRelationship(relationship=dangling),)
    )
    report = edit_and_validate(text, change_set, source_id="e.yaml")
    unresolved = [
        d for d in report.report.diagnostics if d.code == "CORE.RELATION.UNRESOLVED_ENDPOINT"
    ]
    assert len(unresolved) == 1
    where = unresolved[0].source_location
    assert where is not None
    line = report.text.splitlines()[where.line - 1]  # type: ignore[operator]
    assert "nowhere-1" in line
    assert dict(unresolved[0].context)["location_resolution"] == "exact"
    assert not report.edit.delta.is_empty
