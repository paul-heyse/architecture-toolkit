"""Diagnostics resolve to source file, line and column (CORE-19) — the M1 hard gate for W2."""

from pathlib import Path

import pytest

from architecture_toolkit.domain.source import LocationResolution
from architecture_toolkit.validation.authoring import SourceValidation, validate_source_text
from architecture_toolkit.validation.diagnostics import Diagnostic
from architecture_toolkit.validation.locate import locate_diagnostic
from architecture_toolkit.validation.render import render_diagnostics

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
NESTED = ROOT / "tests" / "fixtures" / "authoring" / "nested_foreign_key.yaml"


def _position_of(text: str, needle: str) -> tuple[int, int]:
    """1-based line and column of the first occurrence of `needle`."""
    for number, line in enumerate(text.splitlines(), 1):
        column = line.find(needle)
        if column >= 0:
            return number, column + 1
    raise AssertionError(f"{needle!r} not in text")


def _resolution(diagnostic: Diagnostic) -> str:
    return dict(diagnostic.context)["location_resolution"]


def _only(result: SourceValidation, code: str) -> Diagnostic:
    found = [d for d in result.diagnostics if d.code == code]
    assert len(found) == 1, [d.code for d in result.diagnostics]
    return found[0]


# -- the hard gate ------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-19", "CORE-18")
def test_a_nested_cross_record_failure_resolves_to_its_exact_line_and_column() -> None:
    """agent-handoff.md, M1: nested validation resolves to source location.

    The fixture is the example with one foreign key, four levels deep, pointing at an element
    that does not exist. The rule reports it by canonical ID and identity-grammar field path; the
    SourceMap resolves that to the scalar the author wrote.
    """
    text = NESTED.read_text()
    result = validate_source_text(text, source_id=str(NESTED))
    assert result.outcome == "validated"
    diagnostic = _only(result, "CORE.INTERFACE.UNRESOLVED_FOREIGN_KEY")
    assert _resolution(diagnostic) == LocationResolution.EXACT.value
    where = diagnostic.source_location
    assert where is not None
    # The needle carries the trailing comma so the fixture's header comment cannot match first.
    assert (where.line, where.column) == _position_of(text, "ghost,")
    assert where.semantic_path == "elements[7].detail.fields[1].references_element_id"
    assert where.source_id == str(NESTED)
    assert where.document_id == "sample-service"
    rendered = render_diagnostics([diagnostic], source=str(NESTED))
    line, column = _position_of(text, "ghost,")
    assert rendered.splitlines()[0] == f"{NESTED}:{line}:{column}"
    assert "(nearest" not in rendered


@pytest.mark.unit
@pytest.mark.requirement("CORE-19")
def test_a_record_level_pydantic_failure_resolves_through_the_semantic_path() -> None:
    text = EXAMPLE.read_text().replace("timeout_ms: 30000", "timeout_ms: soon")
    result = validate_source_text(text, source_id="e.yaml")
    assert result.outcome == "invalid_records"
    (diagnostic,) = result.diagnostics
    assert diagnostic.code == "CORE.DOMAIN.INVALID_TYPE"
    assert _resolution(diagnostic) == LocationResolution.PATH.value
    assert diagnostic.source_location is not None
    assert (diagnostic.source_location.line, diagnostic.source_location.column) == _position_of(
        text, "soon"
    )
    assert diagnostic.field_path == "elements[5].detail.timeout_ms"


@pytest.mark.unit
@pytest.mark.requirement("CORE-19")
def test_an_unknown_field_points_at_the_key_the_author_typed() -> None:
    text = EXAMPLE.read_text().replace(
        "    name: Reviewer\n", "    name: Reviewer\n    colour: red\n"
    )
    result = validate_source_text(text, source_id="e.yaml")
    (diagnostic,) = result.diagnostics
    assert diagnostic.code == "CORE.DOMAIN.UNKNOWN_FIELD"
    assert diagnostic.source_location is not None
    assert (diagnostic.source_location.line, diagnostic.source_location.column) == _position_of(
        text, "colour"
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-19")
def test_a_missing_field_falls_back_to_the_record_and_says_so() -> None:
    text = EXAMPLE.read_text().replace("    name: Reviewer\n", "")
    result = validate_source_text(text, source_id="e.yaml")
    (diagnostic,) = result.diagnostics
    assert diagnostic.code == "CORE.DOMAIN.MISSING_REQUIRED_FIELD"
    assert _resolution(diagnostic) == LocationResolution.PARENT.value
    assert diagnostic.source_location is not None
    assert diagnostic.source_location.semantic_path == "elements[2]"
    assert (diagnostic.source_location.line, diagnostic.source_location.column) == _position_of(
        text, "element_id: role-1"
    )
    rendered = render_diagnostics([diagnostic], source="e.yaml")
    assert rendered.splitlines()[0].endswith("(nearest: elements[2])")


@pytest.mark.unit
@pytest.mark.requirement("CORE-19")
def test_a_diagnostic_with_no_anchor_resolves_to_the_document_honestly() -> None:
    """`acyclic` names neither an object nor a field; the chain ends at the document."""
    text = EXAMPLE.read_text() + (
        "  - {relationship_id: rel-9, model_id: sample-service, relationship_type_id: contains,\n"
        "     source_element_id: component-1, target_element_id: system-1}\n"
    )
    # Appending to the end lands the item in the last sequence; move it under relationships.
    text = text.replace(
        "     source_element_id: system-1, target_element_id: role-1}\n",
        "     source_element_id: system-1, target_element_id: role-1}\n"
        "  - {relationship_id: rel-9, model_id: sample-service, relationship_type_id: contains,\n"
        "     source_element_id: component-1, target_element_id: system-1}\n",
        1,
    ).rsplit("  - {relationship_id: rel-9", 1)[0]
    result = validate_source_text(text, source_id="e.yaml")
    assert result.outcome == "validated"
    diagnostic = _only(result, "CORE.CONTAINMENT.CYCLE")
    assert _resolution(diagnostic) == LocationResolution.DOCUMENT.value
    assert diagnostic.source_location is not None
    assert (diagnostic.source_location.line, diagnostic.source_location.column) == (7, 1)
    rendered = render_diagnostics([diagnostic], source="e.yaml")
    assert rendered.splitlines()[0] == "e.yaml:7:1 (nearest: (document))"


@pytest.mark.unit
@pytest.mark.requirement("CORE-19")
def test_a_record_addressed_only_by_identity_resolves_to_the_record() -> None:
    """`single-parent` names the child element and no field: the record is the exact location."""
    text = EXAMPLE.read_text().replace(
        "     source_element_id: system-1, target_element_id: role-1}\n",
        "     source_element_id: system-1, target_element_id: role-1}\n"
        "  - {relationship_id: rel-9, model_id: sample-service, relationship_type_id: contains,\n"
        "     source_element_id: capability-1, target_element_id: component-1}\n",
    )
    result = validate_source_text(text, source_id="e.yaml")
    diagnostic = _only(result, "CORE.CONTAINMENT.MULTIPLE_PARENTS")
    assert _resolution(diagnostic) == LocationResolution.EXACT.value
    assert diagnostic.source_location is not None
    assert diagnostic.source_location.semantic_path == "elements[4]"
    # A record's mapping node starts at its first key, two columns after the sequence dash.
    line, column = _position_of(text, "- element_id: component-1")
    assert (diagnostic.source_location.line, diagnostic.source_location.column) == (
        line,
        column + 2,
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-19")
def test_dotted_identifiers_are_never_split() -> None:
    """`software.system.billing` is a legal ID; tokenizing the identity grammar would break it."""
    text = (
        "model_id: dotted\n"
        "elements:\n"
        "  - element_id: software.system.billing\n"
        "    model_id: dotted\n"
        "    kind_id: software.interface\n"
        "    name: Billing API\n"
        "    detail:\n"
        "      detail_family: interface\n"
        "      element_id: software.system.billing\n"
        "      transport: {protocol: https, interaction_mode: synchronous, serialization: json}\n"
        "      request_schema_id: no.such.schema\n"
    )
    result = validate_source_text(text, source_id="d.yaml")
    diagnostic = _only(result, "CORE.INTERFACE.UNRESOLVED_SCHEMA")
    assert diagnostic.field_path == "elements.software.system.billing.detail.request_schema_id"
    assert _resolution(diagnostic) == LocationResolution.EXACT.value
    assert diagnostic.source_location is not None
    assert diagnostic.source_location.semantic_path == "elements[0].detail.request_schema_id"
    assert (diagnostic.source_location.line, diagnostic.source_location.column) == _position_of(
        text, "no.such.schema"
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-19", "CORE-11")
def test_locating_never_changes_a_diagnostics_identity() -> None:
    text = NESTED.read_text()
    result = validate_source_text(text, source_id="n.yaml")
    assert result.source_map is not None
    for located in result.diagnostics:
        bare = located.model_validate(
            dict(located)
            | {
                "source_location": None,
                "context": tuple(p for p in located.context if p[0] != "location_resolution"),
            }
        )
        again = locate_diagnostic(bare, result.source_map)
        assert again.diagnostic_id == bare.diagnostic_id == located.diagnostic_id
        assert again == located


@pytest.mark.unit
@pytest.mark.requirement("CORE-19")
def test_every_diagnostic_of_the_example_is_located() -> None:
    result = validate_source_text(EXAMPLE.read_text(), source_id="e.yaml")
    assert result.outcome == "validated"
    assert result.diagnostics, "the example carries two deliberate gaps"
    for diagnostic in result.diagnostics:
        assert diagnostic.source_location is not None
        assert diagnostic.source_location.line is not None
        assert _resolution(diagnostic) in {r.value for r in LocationResolution}
