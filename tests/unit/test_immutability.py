"""Deep immutability of the compiled family, enforced totally rather than by review (CORE-08).

`frozen=True` blocks attribute assignment and nothing else. Measured against the pinned Pydantic:
a `dict` field on a frozen model is still mutable *through* the frozen model. So "use immutable
nested field types" cannot be a convention — a reviewer has to notice it every time, and one miss
publishes a mutable record.

Two mechanisms are used together because each covers what the other misses. A static scan over
every `CompiledRecord` subclass is total across *classes* and catches a `dict` declared directly.
A hashability check is semantic and catches a mutable type buried in a nested record the scan
would have to recurse to find — verified catching an offender two levels down. W4's strategies
make the hashability half total across *instances* too.
"""

import json
import typing
from typing import Annotated, Literal, get_args, get_origin

import pytest
from pydantic import BaseModel, Field, ValidationError

from architecture_toolkit.domain.base import AuthoringRecord, CompiledRecord
from architecture_toolkit.domain.registry import BASELINE_PROFILE

MUTABLE_ORIGINS = (list, dict, set)


def concrete_subclasses(root: type[BaseModel]) -> list[type[BaseModel]]:
    """Every shipped subclass, transitively.

    Restricted to the package on purpose. The negative controls below are declared inside test
    functions, which makes them real subclasses the moment their test runs — so an unrestricted
    walk would pass or fail depending on test order. Proven: running the leak test first turns
    the scan red. Filtering by module keeps the scan total over shipped code, which is the thing
    it is meant to be total over.
    """
    found: list[type[BaseModel]] = []
    for subclass in root.__subclasses__():
        if subclass.__module__.startswith("architecture_toolkit."):
            found.append(subclass)
        found.extend(concrete_subclasses(subclass))
    return found


def mutable_containers(annotation: object) -> list[str]:
    """Every mutable container origin reachable in an annotation, including inside unions."""
    origin = get_origin(annotation)
    found: list[str] = []
    if origin in MUTABLE_ORIGINS:
        found.append(getattr(origin, "__name__", str(origin)))
    if annotation in MUTABLE_ORIGINS:
        found.append(getattr(annotation, "__name__", str(annotation)))
    for argument in get_args(annotation):
        found.extend(mutable_containers(argument))
    return found


@pytest.mark.unit
@pytest.mark.requirement("CORE-08")
def test_no_compiled_record_declares_a_mutable_container() -> None:
    """Total across classes. Discovery is by subclass walk, so a new record is covered on sight."""
    offenders = {
        f"{subclass.__name__}.{name}": containers
        for subclass in concrete_subclasses(CompiledRecord)
        for name, field in subclass.model_fields.items()
        if (containers := mutable_containers(field.annotation))
    }
    assert not offenders, f"compiled records must use tuple/frozenset: {offenders}"


@pytest.mark.unit
@pytest.mark.requirement("CORE-08")
def test_compiled_records_are_frozen_and_strict() -> None:
    for subclass in concrete_subclasses(CompiledRecord):
        config = subclass.model_config
        assert config.get("frozen") is True, subclass.__name__
        assert config.get("strict") is True, subclass.__name__
        assert config.get("extra") == "forbid", subclass.__name__


@pytest.mark.unit
@pytest.mark.requirement("CORE-08")
def test_the_baseline_profile_tree_is_hashable() -> None:
    """The semantic half of the guard, over the deepest compiled tree W1 has."""
    assert isinstance(hash(BASELINE_PROFILE), int)
    for kind in BASELINE_PROFILE.kinds:
        assert isinstance(hash(kind), int)
    for entry in BASELINE_PROFILE.relationship_types:
        assert isinstance(hash(entry), int)


@pytest.mark.unit
@pytest.mark.requirement("CORE-08")
def test_hashability_catches_a_mutable_field_nested_two_levels_down() -> None:
    """The negative control. Without this the guard above could be passing vacuously."""

    class _Inner(CompiledRecord):
        payload: dict[str, int]

    class _Middle(CompiledRecord):
        inner: _Inner

    class _Outer(CompiledRecord):
        middle: _Middle

    offender = _Outer(middle=_Middle(inner=_Inner(payload={"a": 1})))
    with pytest.raises(TypeError, match="unhashable type"):
        hash(offender)
    # and the static scan finds it too, at the level where it was declared
    assert mutable_containers(_Inner.model_fields["payload"].annotation) == ["dict"]


@pytest.mark.unit
@pytest.mark.requirement("CORE-08")
def test_frozen_alone_would_not_have_caught_it() -> None:
    """Why the guard is hashability rather than `frozen=True`.

    Assignment is blocked, yet the dict is mutated through the frozen model. This is the exact
    gap the requirement's "immutable nested field types" clause exists to close.
    """

    class _Leaky(CompiledRecord):
        payload: dict[str, int]

    record = _Leaky(payload={"a": 1})
    with pytest.raises(ValidationError, match="frozen"):
        # pyrefly: ignore[read-only]
        # Deliberate. Pyrefly rejects this statically, which is the stronger guard and the one
        # that matters day to day; the runtime assertion exists to show that the static rule and
        # the runtime behaviour agree, and that neither of them stops the mutation two lines
        # below. Suppressed narrowly per CORE-60 — no baseline file, one code, stated reason.
        record.payload = {"b": 2}
    record.payload["a"] = 99
    assert record.payload == {"a": 99}


@pytest.mark.unit
@pytest.mark.requirement("CORE-02")
def test_authoring_input_must_arrive_as_json_not_python_lists() -> None:
    """Why the authoring family is list-shaped and compiled records are built from tuples.

    Under `strict=True`, handing a Python `list` to a `tuple[...]` field fails with the error
    location collapsed to the field itself — every nested error underneath is discarded. The same
    payload through `model_validate_json` reports the full path. A diagnostic layer built on the
    first shape could never point at the field that was actually wrong.
    """

    class _Leaf(CompiledRecord):
        name: str

    class _Root(CompiledRecord):
        leaves: tuple[_Leaf, ...]

    payload = {"leaves": [{"name": 123}]}

    with pytest.raises(ValidationError) as via_python:
        _Root.model_validate(payload)
    collapsed = [error["loc"] for error in via_python.value.errors(include_url=False)]
    assert collapsed == [("leaves",)]

    with pytest.raises(ValidationError) as via_json:
        _Root.model_validate_json(json.dumps(payload))
    full = [error["loc"] for error in via_json.value.errors(include_url=False)]
    assert full == [("leaves", 0, "name")]


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_a_matched_discriminated_variant_injects_its_tag_into_the_error_location() -> None:
    """Pinned here because `validation/` has to strip that segment to build a usable field path."""

    class _A(CompiledRecord):
        tag: Literal["a"] = "a"
        value: int

    class _B(CompiledRecord):
        tag: Literal["b"] = "b"
        other: str

    class _Holder(CompiledRecord):
        detail: Annotated[_A | _B, Field(discriminator="tag")]

    with pytest.raises(ValidationError) as caught:
        _Holder.model_validate_json(json.dumps({"detail": {"tag": "a", "value": "no"}}))
    assert [error["loc"] for error in caught.value.errors(include_url=False)] == [
        ("detail", "a", "value")
    ]


@pytest.mark.unit
@pytest.mark.requirement("CORE-02")
def test_both_families_reject_undeclared_fields() -> None:
    for base in (AuthoringRecord, CompiledRecord):

        class _Closed(base):  # type: ignore[misc, valid-type]
            known: str

        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            _Closed.model_validate_json(json.dumps({"known": "x", "surprise": 1}))


@pytest.mark.unit
@pytest.mark.requirement("CORE-08")
def test_the_two_families_are_configured_differently_on_purpose() -> None:
    assert AuthoringRecord.model_config.get("frozen") is True
    assert CompiledRecord.model_config.get("frozen") is True
    assert typing.get_type_hints(BASELINE_PROFILE.__class__)  # annotations resolve
