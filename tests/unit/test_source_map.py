"""Plain data and the SourceMap (CORE-17, CORE-18)."""

import json
from pathlib import Path
from types import NoneType
from typing import Any

import pytest
from hypothesis import given, settings

from architecture_toolkit.domain.authoring import LoadedSource, parse_source
from architecture_toolkit.domain.authoring.plain import IDENTITY_KEYS
from architecture_toolkit.domain.semantics import MODEL_COLLECTIONS
from architecture_toolkit.domain.source import (
    SourceEntry,
    SourceLocation,
    SourceMap,
    render_segments,
    split_path,
)
from architecture_toolkit.validation.normalize import field_path
from tests.strategies.relations import full_models

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
PLAIN_TYPES = {str, int, float, bool, NoneType, tuple, dict}


@pytest.fixture(scope="module")
def example() -> LoadedSource:
    """Module-scoped: the loaded source is immutable (frozen dataclass over a read-only map)."""
    return parse_source(EXAMPLE.read_text(), source_id="examples/minimal/model.yaml")


def _types(value: object, seen: set[type]) -> set[type]:
    seen.add(type(value))
    if isinstance(value, dict):
        for inner in value.values():
            _types(inner, seen)
    if isinstance(value, tuple):
        for inner in value:
            _types(inner, seen)
    return seen


def _resolve(data: Any, segments: tuple[str | int, ...]) -> Any:
    current = data
    for segment in segments:
        current = current[segment]
    return current


# -- CORE-17: nothing ruamel escapes ---------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-17")
def test_plain_data_is_exactly_the_primitive_types(example: LoadedSource) -> None:
    """Checked by identity, so a `ScalarString` cannot pass as a `str`."""
    assert _types(example.data, set()) <= PLAIN_TYPES
    for value in (example.data, example.source_map, example.source_map.root):
        assert not type(value).__module__.startswith("ruamel")


@pytest.mark.property
@pytest.mark.slow
@pytest.mark.requirement("CORE-17", "CORE-45")
@settings(max_examples=30, deadline=None)
@given(full_models())
def test_rendered_models_reload_as_primitive_types(model: object) -> None:
    from architecture_toolkit.domain.authoring.profile import dump_text
    from architecture_toolkit.domain.model import Model

    assert isinstance(model, Model)
    text = dump_text(json.loads(model.model_dump_json(exclude_none=True)))
    loaded = parse_source(text, source_id="generated.yaml")
    assert _types(loaded.data, set()) <= PLAIN_TYPES


@pytest.mark.unit
@pytest.mark.requirement("CORE-17")
def test_an_implicit_timestamp_stays_a_string() -> None:
    loaded = parse_source("model_id: demo\nwhen: 2024-01-01\nnum: 0x1F\n", source_id="t")
    assert loaded.data == {"model_id": "demo", "when": "2024-01-01", "num": 31}
    assert type(loaded.data["when"]) is str
    assert type(loaded.data["num"]) is int


# -- CORE-18: the map ----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-18")
def test_every_entry_resolves_in_the_plain_data(example: LoadedSource) -> None:
    for path, entry in example.source_map.entries.items():
        assert entry.path == path
        assert render_segments(entry.segments) == path
        assert split_path(path) == entry.segments
        _resolve(example.data, entry.segments)  # raises if the path does not exist


@pytest.mark.unit
@pytest.mark.requirement("CORE-18")
def test_positions_are_one_based_and_carry_extents(example: LoadedSource) -> None:
    text = EXAMPLE.read_text().splitlines()
    source_map = example.source_map

    def text_at(location: SourceLocation) -> str:
        assert location.line is not None
        assert location.column is not None
        assert location.end_column is not None
        return text[location.line - 1][location.column - 1 : location.end_column]

    assert text_at(source_map.entries["model_id"].value) == "sample-service"
    # A scalar inside a flow mapping inside a block sequence.
    nested = source_map.entries["elements[7].detail.fields[1].references_element_id"]
    assert text_at(nested.value) == "role-1"
    assert nested.key is not None
    assert text_at(nested.key) == "references_element_id"
    # A quoted scalar starts at its quote.
    assert text_at(source_map.entries["schema_version"].value) == '"1.0.0"'
    # A block collection spans to its last child.
    elements = source_map.entries["elements"].value
    assert elements.line == 12
    assert elements.end_line is not None
    assert elements.end_line > 130
    # The root mapping starts at the first key, after the leading comment block.
    assert (source_map.root.line, source_map.root.column) == (7, 1)
    assert source_map.root.source_id == "examples/minimal/model.yaml"


@pytest.mark.unit
@pytest.mark.requirement("CORE-18")
def test_identity_paths_cover_every_record_in_the_example(example: LoadedSource) -> None:
    source_map = example.source_map
    for collection, key in MODEL_COLLECTIONS:
        records = example.data[collection]
        assert isinstance(records, tuple)
        for index, record in enumerate(records):
            assert isinstance(record, dict)
            identity = record[key]
            assert isinstance(identity, str)
            assert source_map.record_paths[identity] == (f"{collection}.{identity}",)
            entry = source_map.lookup_identity(f"{collection}.{identity}")
            assert entry is not None
            assert entry.path == f"{collection}[{index}]"
    # Nested identities, and positional items under an identity prefix.
    field = source_map.lookup_identity("elements.schema-1.detail.fields.submitted_by")
    assert field is not None
    assert field.path == "elements[7].detail.fields[1]"
    participant = source_map.lookup("interactions[0].participants[1]")
    assert participant is not None
    assert participant.identity_path == "interactions.handoff-1.participants.role-1"
    moved = source_map.lookup("interactions[0].moved_object_ids[0]")
    assert moved is not None
    assert moved.identity_path == "interactions.handoff-1.moved_object_ids.0"
    # Every top-level collection's identity field must be an identity key, or a diagnostic
    # addressed at one of its records silently loses its source location. `>=` because
    # `IDENTITY_KEYS` also covers nested records — fields, nodes, transitions.
    assert set(IDENTITY_KEYS) >= {key for _, key in MODEL_COLLECTIONS}
    # A mention of an identity inside another record is not a record path.
    assert source_map.record_paths["process-1"] == ("elements.process-1",)
    assert "triage" not in source_map.record_paths


@pytest.mark.unit
@pytest.mark.requirement("CORE-18", "CORE-19")
def test_nearest_falls_back_one_segment_at_a_time(example: LoadedSource) -> None:
    source_map = example.source_map
    entry, matched = source_map.nearest(("elements", 7, "detail", "fields", 9, "x"))
    assert entry is not None
    assert entry.path == "elements[7].detail.fields"
    assert matched == 4
    entry, matched = source_map.nearest(("nothing", "here"))
    assert entry is not None
    assert entry.path == ""
    assert matched == 0
    assert entry.value == source_map.root


@pytest.mark.unit
@pytest.mark.requirement("CORE-18")
def test_the_map_records_its_provenance(example: LoadedSource) -> None:
    source_map = example.source_map
    assert source_map.document_id == "sample-service"
    assert source_map.source_digest.startswith("sha256:")
    assert source_map.profile_version == "1"
    assert source_map.parser_version
    assert isinstance(source_map, SourceMap)
    assert isinstance(source_map.entries[""], SourceEntry)


@pytest.mark.unit
@pytest.mark.requirement("CORE-18")
def test_loading_is_deterministic() -> None:
    text = EXAMPLE.read_text()
    first = parse_source(text, source_id="e").source_map
    second = parse_source(text, source_id="e").source_map
    assert first == second


# -- one grammar -------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-18", "CORE-19")
def test_pydantic_paths_and_source_map_paths_share_one_grammar() -> None:
    loc: tuple[str | int, ...] = ("elements", 7, "detail", "fields", 1, "references_element_id")
    assert field_path(None, loc) == render_segments(loc)
    assert split_path(render_segments(loc)) == loc
    assert render_segments(()) == ""
    assert split_path("") == ()
    assert render_segments((0, "a")) == "[0].a"
