"""The bounded extension field, and the rule that nothing may query it (DATA-13)."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.extensions import (
    MAX_EXTENSION_VALUE_LENGTH,
    MAX_EXTENSIONS_PER_RECORD,
    Extension,
    duplicate_extension_key,
)
from architecture_toolkit.domain.model import Element, Relationship

SRC = Path(__file__).resolve().parents[2] / "src" / "architecture_toolkit"

# Where reading an extension would mean it had become part of the model's meaning. `storage/` is
# absent on purpose: persisting the column is exactly what DATA-13 asks for, and `domain/` holds
# the declaration itself.
CONSUMER_PACKAGES = ("queries", "projections", "validation/rules")


def _element(extensions: tuple[Extension, ...] = ()) -> Element:
    return Element(
        element_id="elt-1",
        model_id="mod-1",
        kind_id="software.system",
        name="A system",
        extensions=extensions,
    )


@pytest.mark.unit
@pytest.mark.requirement("DATA-13")
def test_an_element_and_a_relationship_carry_extensions() -> None:
    extension = Extension(namespace="acme.finance", key="cost_centre", value="CC-42")
    element = _element((extension,))
    relationship = Relationship(
        relationship_id="rel-1",
        model_id="mod-1",
        relationship_type_id="contains",
        source_element_id="elt-1",
        target_element_id="elt-2",
        extensions=(extension,),
    )
    assert element.extensions == (extension,)
    assert relationship.extensions == (extension,)


@pytest.mark.unit
@pytest.mark.requirement("DATA-13")
def test_the_field_is_bounded_at_sixteen_entries() -> None:
    def make(count: int) -> tuple[Extension, ...]:
        return tuple(
            Extension(namespace="acme.finance", key=f"k{index}", value="v")
            for index in range(count)
        )

    assert _element(make(MAX_EXTENSIONS_PER_RECORD)).extensions
    with pytest.raises(ValidationError, match="at most 16"):
        _element(make(MAX_EXTENSIONS_PER_RECORD + 1))


@pytest.mark.unit
@pytest.mark.requirement("DATA-13")
def test_a_value_is_bounded_and_a_namespace_needs_two_segments() -> None:
    long_value = "x" * (MAX_EXTENSION_VALUE_LENGTH + 1)
    with pytest.raises(ValidationError):
        Extension(namespace="acme.finance", key="k", value=long_value)
    with pytest.raises(ValidationError):
        Extension(namespace="acme", key="k", value="v")
    assert Extension(namespace="acme.finance.tax", key="k", value="").value == ""


@pytest.mark.unit
@pytest.mark.requirement("DATA-13")
def test_a_repeated_namespace_and_key_is_refused_on_both_records() -> None:
    pair = (
        Extension(namespace="acme.finance", key="owner", value="a"),
        Extension(namespace="acme.finance", key="owner", value="b"),
    )
    assert duplicate_extension_key(pair) == ("acme.finance", "owner")
    with pytest.raises(ValidationError, match=r"repeats extension acme\.finance\.owner"):
        _element(pair)
    with pytest.raises(ValidationError, match=r"repeats extension acme\.finance\.owner"):
        Relationship(
            relationship_id="rel-1",
            model_id="mod-1",
            relationship_type_id="contains",
            source_element_id="elt-1",
            target_element_id="elt-2",
            extensions=pair,
        )
    # The same key under a different namespace is a different annotation, not a duplicate.
    assert (
        duplicate_extension_key(
            (
                Extension(namespace="acme.finance", key="owner", value="a"),
                Extension(namespace="acme.legal", key="owner", value="b"),
            )
        )
        is None
    )


def _reads_extensions(source: str) -> bool:
    """Does this source read an `extensions` attribute or subscript anywhere?"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "extensions":
            return True
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "extensions"
        ):
            return True
    return False


@pytest.mark.unit
@pytest.mark.requirement("DATA-13")
def test_the_scan_that_enforces_the_rule_catches_a_known_bad_reading() -> None:
    """The guard below is only worth having if it fails on the thing it claims to catch."""
    assert _reads_extensions("def rule(element):\n    return element.extensions\n")
    assert _reads_extensions("def rule(row):\n    return row['extensions']\n")
    assert not _reads_extensions("def rule(element):\n    return element.name\n")


@pytest.mark.unit
@pytest.mark.requirement("DATA-13")
def test_no_query_projection_or_rule_reads_an_extension() -> None:
    """An extension is an annotation nobody queries.

    The moment one is read by a query recipe, a projection or a validation rule it has stopped
    being an annotation and become part of the model's meaning, and it graduates to a typed field
    through a DATA-56 migration. This is that rule, executable.
    """
    scanned: list[Path] = []
    for package in CONSUMER_PACKAGES:
        directory = SRC / package
        # A renamed package would make this scan silently vacuous, which is the failure mode
        # `docs/contract-enforcement.md` warns about: a guard that matches nothing reads exactly
        # like a guard that found nothing.
        assert directory.is_dir(), f"{package} is not a package any more; update this guard"
        scanned.extend(directory.rglob("*.py"))

    assert scanned, "the guard scanned no files at all"
    offenders = [
        path.relative_to(SRC).as_posix() for path in scanned if _reads_extensions(path.read_text())
    ]
    assert not offenders, f"extensions read outside storage and domain: {offenders}"
