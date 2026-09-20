"""Deterministic validation context (CORE-06).

`ARCH-TOOL-CORE-001` §3G fixes the four fields and the prohibition: no network or database
lookup, and no hidden mutable client facts, inside a record validator. The record is frozen and
hashable so it cannot become a mutable carrier for the second of those, and `no-io-in-validation`
enforces the first structurally rather than by comment.

Pydantic carries this through `model_validate(..., context=...)`, which propagates into nested
models and through `TypeAdapter` — verified against the pinned version. `require_context` is the
single narrowing point, because `info.context` is typed `Any` and scattering casts around the
validators would put the type hole everywhere instead of in one reviewed place.
"""

from enum import StrEnum
from typing import Any

from pydantic import ValidationInfo
from pydantic_core import PydanticCustomError

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import ProfileVersion, SchemaVersion

__all__ = ["CONTEXT_KEY", "FeatureFlag", "ValidationContext", "ValidationMode", "require_context"]

CONTEXT_KEY = "architecture_validation"


class ValidationMode(StrEnum):
    AUTHORING = "authoring"
    CANDIDATE = "candidate"
    RELEASE = "release"


class FeatureFlag(StrEnum):
    """Closed, so a flag is a reviewed addition rather than a string someone passed once."""

    STRICT_PROFILE_EXPECTATIONS = "strict_profile_expectations"


class ValidationContext(CompiledRecord):
    schema_version: SchemaVersion
    profile_version: ProfileVersion
    validation_mode: ValidationMode = ValidationMode.AUTHORING
    enabled_feature_flags: frozenset[FeatureFlag] = frozenset()

    def as_pydantic_context(self) -> dict[str, Any]:
        return {CONTEXT_KEY: self}


def require_context(info: ValidationInfo) -> ValidationContext:
    """Narrow `info.context` once, with a registered code when it is absent."""
    raw = info.context
    found = raw.get(CONTEXT_KEY) if isinstance(raw, dict) else None
    if not isinstance(found, ValidationContext):
        raise PydanticCustomError(
            "CORE.DOMAIN.MISSING_VALIDATION_CONTEXT",
            "this validator requires an explicit ValidationContext",
        )
    return found
