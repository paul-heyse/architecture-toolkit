"""Advanced Pydantic patterns the domain layer relies on must check cleanly (CORE-56).

A runtime Pydantic test and a clean Pyrefly run are separate acceptance signals: the first says
validation behaves, the second says the annotations describe what validation does. This module
covers the second.

Seeded with the patterns `docs/contracts/core.md` names today. W1 and W2 must extend it as they
introduce new ones — a pattern the domain uses but this file does not exercise is unqualified.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self, assert_never, assert_type

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

# CORE-03: centralized constrained aliases rather than repeated raw-string rules.
ElementId = Annotated[str, Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")]
Digest = Annotated[str, Field(min_length=64, max_length=64)]


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
