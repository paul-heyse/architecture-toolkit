"""The semantic aliases, and the one property the Hypothesis guard depends on (CORE-03)."""

import re
from typing import Annotated, Any, get_args, get_origin

import pytest
from pydantic import StringConstraints, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from architecture_toolkit.domain import identifiers


def semantic_aliases() -> dict[str, Any]:
    """Every exported name that is a constrained string alias."""
    found = {}
    for name in identifiers.__all__:
        value = getattr(identifiers, name)
        if get_origin(value) is Annotated:
            found[name] = value
    return found


@pytest.mark.unit
@pytest.mark.requirement("CORE-03")
def test_every_alias_is_constrained_with_string_constraints() -> None:
    """`Field` and `StringConstraints` are not interchangeable here, and the difference is silent.

    Hypothesis cannot read a Pydantic constraint. Given `Annotated[str, StringConstraints(...)]`
    it at least *warns* — `HypothesisWarning: Ignoring unsupported ...` — which `filterwarnings`
    in `pyproject.toml` turns into a hard failure. Given `Annotated[str, Field(pattern=...)]` it
    emits nothing at all and yields values that fail validation. Both were measured against the
    pinned versions.

    So the guard against a mis-generated strategy only exists while every alias uses
    `StringConstraints`. Switching one to `Field` would keep every other test passing and quietly
    disable it, which is exactly the class of rot this repository treats as a defect.
    """
    offenders = {
        name: [type(m).__name__ for m in get_args(alias)[1:] if isinstance(m, FieldInfo)]
        for name, alias in semantic_aliases().items()
    }
    assert not {n: m for n, m in offenders.items() if m}, (
        "these aliases use Field(...) instead of StringConstraints(...), which disables the "
        "Hypothesis warning guard"
    )
    for name, alias in semantic_aliases().items():
        metadata = get_args(alias)[1:]
        assert any(isinstance(m, StringConstraints) for m in metadata), name


@pytest.mark.unit
@pytest.mark.requirement("CORE-03")
def test_patterns_are_anchored() -> None:
    """Pydantic's `pattern` is a search, not a full match.

    Unanchored, `IDENTIFIER_PATTERN` accepts `"XX abc XX"`. Verified against the pinned version,
    which is why every constant here carries its own anchors rather than relying on the caller.
    """
    for name in (
        "IDENTIFIER_PATTERN",
        "QUALIFIED_KIND_PATTERN",
        "DIGEST_PATTERN",
        "VERSION_PATTERN",
    ):
        pattern = getattr(identifiers, name)
        assert pattern.startswith("^"), name
        assert pattern.endswith("$"), name


@pytest.mark.unit
@pytest.mark.requirement("CORE-03")
@pytest.mark.parametrize(
    ("alias", "accepted", "rejected"),
    [
        (identifiers.ElementId, "req-1", "Req-1"),
        (identifiers.ElementId, "software.system.billing", "ab"),
        (identifiers.QualifiedKind, "software.interface", "software"),
        (identifiers.QualifiedKind, "motivation.requirement", "software.interface.http"),
        (identifiers.Digest, "sha256:" + "0" * 64, "0" * 64),
        (identifiers.SchemaVersion, "1.0.0", "1.0"),
        (identifiers.SchemaVersion, "0.1.0", "01.0.0"),
    ],
)
def test_alias_accepts_and_rejects(alias: Any, accepted: str, rejected: str) -> None:
    adapter = TypeAdapter(alias)
    assert adapter.validate_python(accepted) == accepted
    with pytest.raises(ValidationError):
        adapter.validate_python(rejected)


@pytest.mark.unit
@pytest.mark.requirement("DATA-31")
def test_semantic_and_layout_digests_are_separate_names() -> None:
    """DATA-31 separates semantic from layout identity.

    They share a pattern, so this cannot be a runtime assertion about values. It is an assertion
    that two distinct names exist for a reader and a type checker, which is the whole mechanism:
    a function returning `LayoutDigest` cannot be read as returning a semantic one.
    """
    assert "SemanticDigest" in identifiers.__all__
    assert "LayoutDigest" in identifiers.__all__
    assert re.fullmatch(identifiers.DIGEST_PATTERN, "sha256:" + "a" * 64)
