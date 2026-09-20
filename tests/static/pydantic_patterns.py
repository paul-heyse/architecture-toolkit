"""Advanced Pydantic patterns the domain layer relies on must check cleanly (CORE-56).

A runtime Pydantic test and a clean Pyrefly run are separate acceptance signals: the first says
validation behaves, the second says the annotations describe what validation does. This module
covers the second.

Seeded with the patterns `docs/contracts/core.md` names today. W1 and W2 must extend it as they
introduce new ones — a pattern the domain uses but this file does not exercise is unqualified.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cached_property
from typing import Annotated, Any, Literal, Self, assert_never, assert_type, get_origin

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

# CORE-03: centralized constrained aliases rather than repeated raw-string rules.
#
# `StringConstraints`, not `Field`, and the choice is load-bearing rather than stylistic. Measured
# against the pinned versions: `st.from_type` on a `StringConstraints` alias raises a
# `HypothesisWarning` that `filterwarnings` turns into a failure, while on a `Field`-constrained
# alias it warns not at all and yields values that fail validation. The seeded form of this file
# used `Field`, which would have qualified the pattern that silently disables the guard.
ElementId = Annotated[str, StringConstraints(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")]
Digest = Annotated[str, StringConstraints(min_length=64, max_length=64)]


class Strict(BaseModel):
    # CORE-02, CORE-08: strict, extra-forbidding, frozen.
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class InterfaceDetail(Strict):
    kind: Literal["interface"]
    element_id: ElementId
    protocol: str


class RequirementDetail(Strict):
    kind: Literal["requirement"]
    element_id: ElementId
    verification: str


# CORE-04: field-discriminated union with a stable tag.
ElementDetail = Annotated[InterfaceDetail | RequirementDetail, Field(discriminator="kind")]


class CompiledModel(Strict):
    model_id: ElementId
    details: tuple[ElementDetail, ...]
    digest: Digest | None = None

    @model_validator(mode="after")
    def at_least_one_detail(self) -> Self:
        if not self.details:
            message = "a compiled model carries at least one detail"
            raise ValueError(message)
        return self


def dispatch(detail: InterfaceDetail | RequirementDetail) -> str:
    """CORE-59: adding a variant must break this statically until it is handled here."""
    match detail:
        case InterfaceDetail():
            assert_type(detail, InterfaceDetail)
            return detail.protocol
        case RequirementDetail():
            assert_type(detail, RequirementDetail)
            return detail.verification
        case _:
            assert_never(detail)


# CORE-05: TypeAdapter at a natural collection boundary, not as a wrapper model.
DETAILS = TypeAdapter(list[ElementDetail])


def parse_details(payload: list[dict[str, object]]) -> list[InterfaceDetail | RequirementDetail]:
    parsed = DETAILS.validate_python(payload)
    assert_type(parsed, list[InterfaceDetail | RequirementDetail])
    return parsed


# -- patterns introduced by W1 ------------------------------------------------------------------
# Each is used by `domain/`, so each has to type-check here or it is unqualified (CORE-56).


class GapState(StrEnum):
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class Disposition(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"


class StatusSlice(Strict):
    """DATA-41: a gap is a value in the union, not a missing field.

    `Disposition | GapState` rather than `Disposition | None`, because a null says nobody wrote
    anything and a `GapState` says we looked. Pyrefly has to accept the union of two `StrEnum`s
    as a field annotation for this to be expressible at all.
    """

    disposition: Disposition | GapState = GapState.UNKNOWN


def describe_status(value: Disposition | GapState) -> str:
    """CORE-59 over the gap union: adding a member to either enum must break this statically."""
    match value:
        case Disposition.PROPOSED:
            return "proposed"
        case Disposition.ACCEPTED:
            return "accepted"
        case GapState.UNKNOWN:
            return "not known"
        case GapState.NOT_APPLICABLE:
            return "not applicable"
        case _ as unreachable:
            assert_never(unreachable)


class ImmutableNested(Strict):
    """CORE-08: immutable nested field types only.

    `tuple` and `frozenset`, never `list`, `set` or `dict`. Pydantic rejects `MappingProxyType`
    outright, so an immutable mapping is spelled as a tuple of pairs.
    """

    names: tuple[str, ...] = ()
    tags: frozenset[str] = frozenset()
    labels: tuple[tuple[str, str], ...] = ()


class CachedRegistry(Strict):
    """A frozen record with an O(1) index and no mutable field.

    `cached_property` writes to the instance `__dict__`, which a frozen Pydantic model permits,
    and the model stays hashable because Pydantic hashes field values. That is what lets a
    profile be a value rather than a loaded file.
    """

    entries: tuple[str, ...] = ()

    @cached_property
    def by_name(self) -> dict[str, int]:
        return {name: index for index, name in enumerate(self.entries)}


def read_cached(registry: CachedRegistry) -> int | None:
    assert_type(registry.by_name, dict[str, int])
    return registry.by_name.get("a")


DETAIL_UNION = TypeAdapter(list[ElementDetail])
"""CORE-05 over a collection boundary; no wrapper model is created to call validation."""


# -- patterns introduced by W2 ------------------------------------------------------------------


def derive(record: CompiledModel, **changes: object) -> CompiledModel:
    """CORE-09: a frozen record is derived through full validation, never `model_copy(update=)`.

    `dict(record)` keeps nested records as instances, and calling `model_validate` through the
    instance types the result as `Self`, which is what lets `domain/semantics.py` stamp digests
    generically over every record family.
    """
    derived = record.model_validate(dict(record) | changes)
    assert_type(derived, CompiledModel)
    return derived


def json_ready(record: CompiledModel) -> dict[str, Any]:
    """JSON-mode dump is the canonical-form input and the round-trip renderer's source."""
    payload = record.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    assert_type(payload, dict[str, Any])
    return payload


def literal_fields(cls: type[BaseModel]) -> set[str]:
    """Discriminators are `Literal` fields with defaults, so `exclude_defaults` drops them.

    A renderer that writes authoring YAML from a record has to put them back, which means it must
    be able to find them from the annotations rather than from a dump.
    """
    return {
        name for name, field in cls.model_fields.items() if get_origin(field.annotation) is Literal
    }


class RecordCarryingError(ValueError):
    """An exception that carries a frozen record: the authoring adapter's error shape."""

    def __init__(self, record: CompiledModel, message: str) -> None:
        super().__init__(message)
        self.record = record

    def identity(self) -> str:
        assert_type(self.record, CompiledModel)
        return self.record.model_id


# -- W3 patterns --------------------------------------------------------------------------------


class BoundedAnnotation(CompiledModel):
    """DATA-13: a bounded tuple field. `max_length` on `Field`, not on the annotation.

    The distinction matters to the generated JSON Schema: `Field(max_length=...)` on a tuple
    emits `maxItems`, which is the keyword a consumer validating authored YAML against
    `schemas/model.schema.json` actually reads.
    """

    entries: tuple[str, ...] = Field(default=(), max_length=16)


def bounded(record: BoundedAnnotation) -> int:
    assert_type(record.entries, tuple[str, ...])
    return len(record.entries)


class _Alpha(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    family: Literal["alpha"] = "alpha"
    a: str


class _Beta(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    family: Literal["beta"] = "beta"
    b: str


_Member = Annotated[_Alpha | _Beta, Field(discriminator="family")]


def route(member: _Member) -> str:
    """CORE-59 over a discriminated union, which is how `compile_tables` routes element detail.

    The point is what happens when a variant is added: `assert_never` stops type-checking and
    every router that does not handle the new family fails `pyrefly check`. That makes W3's
    "five detail tables, one per element-attachable family" a structural fact rather than a
    comment — a sixth family cannot be added without the storage layer being told about it.
    """
    match member:
        case _Alpha():
            return member.a
        case _Beta():
            return member.b
        case _ as unreachable:
            assert_never(unreachable)
