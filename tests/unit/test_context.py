"""Explicit, deterministic validation context (CORE-06)."""

import json
from typing import Self

import pytest
from pydantic import ValidationError, ValidationInfo, model_validator

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.validation.context import (
    FeatureFlag,
    ValidationContext,
    ValidationMode,
    require_context,
)

CONTEXT = ValidationContext(schema_version="1.0.0", profile_version="1.0.0")


class _NeedsContext(CompiledRecord):
    value: str

    @model_validator(mode="after")
    def value_is_allowed_by_the_profile(self, info: ValidationInfo) -> Self:
        context = require_context(info)
        if context.validation_mode is ValidationMode.RELEASE and self.value == "draft":
            message = "a draft value cannot survive into a release"
            raise ValueError(message)
        return self


class _Holder(CompiledRecord):
    nested: tuple[_NeedsContext, ...]


@pytest.mark.unit
@pytest.mark.requirement("CORE-06")
def test_the_context_carries_exactly_the_four_specified_fields() -> None:
    assert set(ValidationContext.model_fields) == {
        "schema_version",
        "profile_version",
        "validation_mode",
        "enabled_feature_flags",
    }


@pytest.mark.unit
@pytest.mark.requirement("CORE-06")
def test_the_context_reaches_a_validator_nested_inside_a_collection() -> None:
    """The mechanism the whole design rests on: `info.context` propagates all the way down."""
    payload = json.dumps({"nested": [{"value": "draft"}]})
    assert _Holder.model_validate_json(payload, context=CONTEXT.as_pydantic_context())

    release = ValidationContext(
        schema_version="1.0.0", profile_version="1.0.0", validation_mode=ValidationMode.RELEASE
    )
    with pytest.raises(ValidationError, match="cannot survive into a release"):
        _Holder.model_validate_json(payload, context=release.as_pydantic_context())


@pytest.mark.unit
@pytest.mark.requirement("CORE-06")
def test_a_missing_context_is_a_registered_code_not_a_crash() -> None:
    with pytest.raises(ValidationError) as caught:
        _NeedsContext.model_validate_json(json.dumps({"value": "draft"}))
    assert {error["type"] for error in caught.value.errors(include_url=False)} == {
        "CORE.DOMAIN.MISSING_VALIDATION_CONTEXT"
    }


@pytest.mark.unit
@pytest.mark.requirement("CORE-06", "CORE-11")
def test_a_custom_code_raised_by_a_validator_survives_normalization() -> None:
    """The bridge between record-local validators and the code registry.

    `PydanticCustomError` accepts the dotted code verbatim, so the normalizer's 104-entry table
    only has to cover Pydantic's own built-ins.
    """
    from architecture_toolkit.validation.normalize import normalize_validation_error

    with pytest.raises(ValidationError) as caught:
        _NeedsContext.model_validate_json(json.dumps({"value": "draft"}))
    codes = {d.code for d in normalize_validation_error(caught.value, root=_NeedsContext)}
    assert codes == {"CORE.DOMAIN.MISSING_VALIDATION_CONTEXT"}


@pytest.mark.unit
@pytest.mark.requirement("CORE-06")
def test_the_context_is_frozen_so_it_cannot_smuggle_mutable_state() -> None:
    """§3G forbids hidden mutable client facts inside record validators."""
    assert isinstance(hash(CONTEXT), int)
    with pytest.raises(ValidationError, match="frozen"):
        # pyrefly: ignore[read-only]
        # Deliberate: Pyrefly rejects this statically, and the runtime assertion records that
        # the static rule and the runtime behaviour agree. CORE-60 narrow suppression.
        CONTEXT.validation_mode = ValidationMode.RELEASE


@pytest.mark.unit
@pytest.mark.requirement("CORE-06")
def test_feature_flags_are_a_closed_vocabulary() -> None:
    """A free-string flag is a flag nobody agreed to."""
    with pytest.raises(ValidationError):
        ValidationContext.model_validate_json(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "profile_version": "1.0.0",
                    "enabled_feature_flags": ["invented_flag"],
                }
            )
        )
    assert FeatureFlag.STRICT_PROFILE_EXPECTATIONS in set(FeatureFlag)
