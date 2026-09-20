"""The configured round-trip profile (CORE-14)."""

from pathlib import Path

import pytest
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from architecture_toolkit.domain.authoring import (
    AUTHORING_PROFILE_VERSION,
    MAX_DEPTH,
    AuthoringError,
    parse_model,
    parse_source,
)
from architecture_toolkit.domain.authoring.profile import INDENT, WIDTH, dump_text, make_yaml
from architecture_toolkit.domain.semantics import model_digest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
CANONICAL = ROOT / "tests" / "fixtures" / "authoring" / "round_trip" / "canonical.yaml"


def _nested(depth: int) -> str:
    lines = ["a:"]
    for level in range(1, depth):
        lines.append("  " * level + f"k{level}:")
    lines.append("  " * depth + "v: 1")
    return "\n".join(lines) + "\n"


@pytest.mark.unit
@pytest.mark.requirement("CORE-14")
def test_the_factory_hands_out_a_fresh_configured_instance_each_time() -> None:
    """The composer's depth counter is per instance and was measured not resetting."""
    first, second = make_yaml(), make_yaml()
    assert first is not second
    for yaml in (first, second):
        assert yaml.preserve_quotes is True
        assert yaml.max_depth == MAX_DEPTH + 1
        assert yaml.width == WIDTH
        assert yaml.allow_duplicate_keys is False
        assert (yaml.map_indent, yaml.sequence_indent, yaml.sequence_dash_offset) == INDENT
        assert yaml.version is None
    assert AUTHORING_PROFILE_VERSION == "1"


@pytest.mark.unit
@pytest.mark.requirement("CORE-14")
def test_yaml_1_2_semantics_are_in_force() -> None:
    """`yes` is a string and `010` is ten; both were booleans and octal under 1.1."""
    loaded = parse_source("model_id: demo\nflag: yes\nnumber: 010\n", source_id="v.yaml")
    assert loaded.data == {"model_id": "demo", "flag": "yes", "number": 10}


@pytest.mark.unit
@pytest.mark.requirement("CORE-14")
def test_depth_is_bounded_at_exactly_the_declared_maximum() -> None:
    assert parse_source(_nested(MAX_DEPTH - 1), source_id="ok.yaml").data
    with pytest.raises(AuthoringError) as caught:
        parse_source(_nested(MAX_DEPTH), source_id="deep.yaml")
    assert caught.value.code == "CORE.YAML.DEPTH_EXCEEDED"
    assert dict(caught.value.context)["max_depth"] == str(MAX_DEPTH)


@pytest.mark.unit
@pytest.mark.requirement("CORE-14")
def test_the_composer_enforces_the_same_bound_as_the_pre_pass() -> None:
    """Defence in depth: ruamel's own `max_depth` rejects exactly what the pre-pass rejects.

    The composer counts nodes rather than collections, so the profile sets its bound one higher;
    this pins that the two boundaries coincide on the same documents.
    """
    from ruamel.yaml.composer import MaxDepthExceededError

    with pytest.raises(MaxDepthExceededError):
        make_yaml().compose(_nested(MAX_DEPTH))
    assert make_yaml().compose(_nested(MAX_DEPTH - 1)) is not None
    assert make_yaml().max_depth == MAX_DEPTH + 1


@pytest.mark.unit
@pytest.mark.requirement("CORE-14", "CORE-21")
def test_the_example_is_a_fixed_point_after_one_pass_and_keeps_its_comments() -> None:
    """Hand-wrapped flow mappings are re-flowed once; after that the profile reproduces itself.

    Byte identity of the shipped example is not claimed — its flow mappings are wrapped by hand,
    which ruamel's emitter re-flows — so the guarantee stated is the one that holds: the dump is
    a fixed point, semantically equal, with every comment preserved.
    """
    text = EXAMPLE.read_text()
    once = dump_text(make_yaml().load(text))
    twice = dump_text(make_yaml().load(once))
    assert once == twice
    assert once.count("#") == text.count("#")
    original = parse_model(parse_source(text, source_id="example"))
    reflowed = parse_model(parse_source(once, source_id="example-reflowed"))
    assert model_digest(original) == model_digest(reflowed)


@pytest.mark.unit
@pytest.mark.requirement("CORE-14")
def test_a_document_in_the_profiles_own_style_round_trips_byte_for_byte() -> None:
    text = CANONICAL.read_text()
    assert dump_text(make_yaml().load(text)) == text
    parse_model(parse_source(text, source_id="canonical"))


@pytest.mark.unit
@pytest.mark.requirement("CORE-14", "CORE-18")
def test_crlf_input_yields_the_same_source_map_lines() -> None:
    text = EXAMPLE.read_text()
    unix = parse_source(text, source_id="e").source_map
    windows = parse_source(text.replace("\n", "\r\n"), source_id="e").source_map
    assert {p: e.value.line for p, e in unix.entries.items()} == {
        p: e.value.line for p, e in windows.entries.items()
    }


# Every character the emitter escapes: C0 controls, DEL, the C1 range, the line and paragraph
# separators, the byte order mark and the backslash. A newline is excluded because it changes the
# representation rather than the split, and `"` because ruamel's own guard already keeps the
# backslash for it.
_ESCAPED_CHARACTERS = (
    [chr(point) for point in range(0x00, 0x20) if point != 0x0A]
    + [chr(0x7F)]
    + [chr(point) for point in range(0x80, 0xA0)]
    + ["\\", chr(0x2028), chr(0x2029), chr(0xFEFF)]
)


@pytest.mark.unit
@pytest.mark.requirement("CORE-14", "CORE-20")
@pytest.mark.parametrize("character", _ESCAPED_CHARACTERS, ids=lambda c: f"U+{ord(c):04X}")
def test_an_escaped_character_past_the_width_never_gains_a_folded_space(character: str) -> None:
    """ruamel drops the line-continuation backslash on a split it did not make at a space.

    The break then folds into a space the author never wrote. `_SafeRoundTripEmitter` withholds
    the split instead. The prefix is long enough that the escape lands past `WIDTH`, and the
    trailing space is what makes ruamel believe the fold is recoverable.
    """
    value = "a" * WIDTH + character + "bbbbb ccccc"
    tree = CommentedMap()
    tree["name"] = DoubleQuotedScalarString(value)
    assert make_yaml().load(dump_text(tree))["name"] == value


@pytest.mark.unit
@pytest.mark.requirement("CORE-14")
def test_a_scalar_with_nothing_to_escape_still_wraps_at_the_width() -> None:
    """The fix withholds the unsafe split only; ordinary long prose still wraps."""
    tree = CommentedMap()
    tree["name"] = DoubleQuotedScalarString(("word " * 60).strip())
    lines = dump_text(tree).splitlines()
    assert len(lines) > 1
    assert all(len(line) <= WIDTH + 1 for line in lines)
