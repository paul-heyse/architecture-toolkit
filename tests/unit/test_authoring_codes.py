"""Forbidden YAML constructs fail deterministically, each with its own code (CORE-15, CORE-16)."""

import re
from pathlib import Path

import pytest

from architecture_toolkit.domain.authoring import AUTHORING_CODES, AuthoringError, parse_source
from architecture_toolkit.validation.codes import CODES, CodeArea
from architecture_toolkit.validation.normalize import normalize_authoring_error
from architecture_toolkit.validation.taxonomy import DiagnosticCategory, Severity

FORBIDDEN = Path(__file__).resolve().parents[1] / "fixtures" / "authoring" / "forbidden"
EXPECT = re.compile(r"^# expect: (CORE\.YAML\.[A-Z_]+) (\d+):(\d+)$")


def _expectation(path: Path) -> tuple[str, int, int]:
    match = EXPECT.match(path.read_text().splitlines()[0])
    assert match, f"{path.name} has no `# expect:` header"
    return match.group(1), int(match.group(2)), int(match.group(3))


def _fail(path: Path) -> AuthoringError:
    with pytest.raises(AuthoringError) as caught:
        parse_source(path.read_text(), source_id=path.name)
    return caught.value


@pytest.mark.unit
@pytest.mark.requirement("CORE-15", "CORE-16")
@pytest.mark.parametrize("path", sorted(FORBIDDEN.glob("*.yaml")), ids=lambda p: p.stem)
def test_each_fixture_fails_with_exactly_its_code_at_its_position(path: Path) -> None:
    """One fixture per code, proving the specific code rather than a generic parse failure."""
    code, line, column = _expectation(path)
    error = _fail(path)
    assert [finding.code for finding in error] == [code]
    assert (error.location.line, error.location.column) == (line, column)
    assert error.location.source_id == path.name


@pytest.mark.unit
@pytest.mark.requirement("CORE-15", "CORE-16")
def test_every_authoring_code_has_a_fixture_and_a_registry_entry() -> None:
    """Totality in both directions: the adapter's codes, the registry's YAML area, the fixtures."""
    registered = {code for code, spec in CODES.items() if spec.area is CodeArea.YAML}
    assert registered == AUTHORING_CODES
    covered = {_expectation(path)[0] for path in FORBIDDEN.glob("*.yaml")}
    assert covered == AUTHORING_CODES
    for code in AUTHORING_CODES:
        assert CODES[code].category is DiagnosticCategory.AUTHORING_PARSE
        assert CODES[code].default_severity is Severity.ERROR


@pytest.mark.unit
@pytest.mark.requirement("CORE-16")
def test_every_violation_in_a_document_is_reported_not_only_the_first() -> None:
    text = "model_id: demo\nbase: &b {x: 1}\nother: *b\nv: !custom 1\n"
    with pytest.raises(AuthoringError) as caught:
        parse_source(text, source_id="three.yaml")
    findings = list(caught.value)
    assert [f.code for f in findings] == [
        "CORE.YAML.ANCHOR",
        "CORE.YAML.ALIAS",
        "CORE.YAML.CUSTOM_TAG",
    ]
    assert [(f.location.line, f.location.column) for f in findings] == [(2, 7), (3, 8), (4, 4)]


@pytest.mark.unit
@pytest.mark.requirement("CORE-16")
def test_the_adapter_refuses_to_raise_an_unregistered_code() -> None:
    from architecture_toolkit.domain.source import SourceLocation

    with pytest.raises(ValueError, match="not an authoring code"):
        AuthoringError("CORE.YAML.INVENTED", "x", location=SourceLocation(source_id="s"))


@pytest.mark.unit
@pytest.mark.requirement("CORE-14")
def test_an_explicit_yaml_1_2_directive_is_accepted() -> None:
    loaded = parse_source("%YAML 1.2\n---\nmodel_id: demo\n", source_id="v12.yaml")
    assert loaded.data == {"model_id": "demo"}


@pytest.mark.unit
@pytest.mark.requirement("CORE-16")
def test_a_quoted_merge_key_is_an_ordinary_key() -> None:
    """Only the plain `<<` is a merge key in YAML; a quoted one is a string and stays one."""
    loaded = parse_source('model_id: demo\n"<<": 1\n', source_id="quoted.yaml")
    assert loaded.data == {"model_id": "demo", "<<": 1}


@pytest.mark.unit
@pytest.mark.requirement("CORE-16")
def test_standard_tags_outside_the_core_schema_are_custom_tags() -> None:
    for text in ("b: !!binary aGk=\n", "s: !!set {a: null}\n", "t: !!timestamp 2024-01-01\n"):
        with pytest.raises(AuthoringError) as caught:
            parse_source("model_id: demo\n" + text, source_id="tag.yaml")
        assert caught.value.code == "CORE.YAML.CUSTOM_TAG"
        assert dict(caught.value.context)["tag"].startswith("tag:yaml.org,2002:")


@pytest.mark.unit
@pytest.mark.requirement("CORE-11", "CORE-16", "CORE-19")
def test_authoring_errors_normalize_into_located_diagnostics() -> None:
    with pytest.raises(AuthoringError) as caught:
        parse_source("model_id: demo\nmodel_id: again\n", source_id="dup.yaml")
    (diagnostic,) = normalize_authoring_error(caught.value)
    assert diagnostic.code == "CORE.YAML.DUPLICATE_KEY"
    assert diagnostic.category is DiagnosticCategory.AUTHORING_PARSE
    assert diagnostic.source_location is not None
    assert (diagnostic.source_location.line, diagnostic.source_location.column) == (2, 1)
    assert diagnostic.field_path == "model_id"
    assert ("location_resolution", "exact") in diagnostic.context
    assert ("key", "model_id") in diagnostic.context
