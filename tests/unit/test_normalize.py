"""Normalizing Pydantic failures into stable diagnostics (CORE-11)."""

import json
import typing
from typing import Any

import pydantic_core
import pytest
from pydantic import ValidationError

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.model import Model
from architecture_toolkit.validation.codes import CODES
from architecture_toolkit.validation.normalize import (
    ERROR_TYPE_CODES,
    field_path,
    normalize_validation_error,
)

PYDANTIC_ERROR_TYPES = frozenset(typing.get_args(pydantic_core.ErrorType))


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_the_map_is_total_over_every_pydantic_error_type() -> None:
    """Both directions, so an upgrade that adds *or removes* a type fails here.

    `pydantic_core.ErrorType` is a `Literal` and therefore enumerable, which turns "we handle
    the common cases" into a property that can actually be checked. Without this, a new error
    type would silently fall through to `CORE.SCHEMA.UNCLASSIFIED` and every report that
    depended on the specific code would quietly degrade.
    """
    mapped = set(ERROR_TYPE_CODES)
    assert PYDANTIC_ERROR_TYPES - mapped == set(), "unmapped pydantic error types"
    assert mapped - PYDANTIC_ERROR_TYPES == set(), "mapped types pydantic no longer defines"
    assert len(PYDANTIC_ERROR_TYPES) == 104


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_every_mapped_code_is_registered() -> None:
    assert set(ERROR_TYPE_CODES.values()) <= set(CODES)


def _invalid_payload() -> dict[str, Any]:
    return {
        "model_id": "m-1",
        "elements": [
            {
                "element_id": "BAD ID",
                "model_id": "m-1",
                "kind_id": "software.interface",
                "name": "API",
                "detail": {
                    "detail_family": "interface",
                    "element_id": "BAD ID",
                    "transport": {
                        "protocol": "https",
                        "interaction_mode": "synchronous",
                        "serialization": "json",
                    },
                    "timeout_ms": "not a number",
                },
            }
        ],
    }


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_the_injected_discriminator_tag_is_stripped_from_the_field_path() -> None:
    """Pydantic inserts the matched variant's tag into the error location.

    The raw location is `('elements', 0, 'detail', 'interface', 'timeout_ms')`, and `interface`
    is the tag, not a field. Emitting it would produce a path that does not exist in the source
    document; blindly dropping any segment matching a tag would mangle a real field named
    `interface`. The walk descends the annotations, so it drops the segment only where the
    annotation genuinely is a discriminated union.
    """
    with pytest.raises(ValidationError) as caught:
        Model.model_validate_json(json.dumps(_invalid_payload()))
    raw_locations = [error["loc"] for error in caught.value.errors(include_url=False)]
    assert ("elements", 0, "detail", "interface", "timeout_ms") in raw_locations

    paths = {d.field_path for d in normalize_validation_error(caught.value, root=Model)}
    assert "elements[0].detail.timeout_ms" in paths
    assert not any(path and ".interface." in path for path in paths)


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_a_real_field_named_like_a_tag_is_not_stripped() -> None:
    """The negative control for the strip.

    A blocklist of tag names would mangle any legitimate field sharing a name with a variant
    tag. Here `interface` is an ordinary field on a record that is not a union at all, and the
    walk must keep it — which it does, because it consults the annotation rather than the name.
    """

    class Payload(CompiledRecord):
        interface: str

    class Holder(CompiledRecord):
        payload: Payload

    assert field_path(Holder, ("payload", "interface")) == "payload.interface"
    # And in the position where it really is a tag, it goes.
    assert field_path(Model, ("elements", 0, "detail", "interface", "timeout_ms")) == (
        "elements[0].detail.timeout_ms"
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_every_produced_path_resolves_in_the_source_document() -> None:
    """The property that makes the walk trustworthy rather than plausible."""
    payload = _invalid_payload()
    with pytest.raises(ValidationError) as caught:
        Model.model_validate_json(json.dumps(payload))

    for diagnostic in normalize_validation_error(caught.value, root=Model):
        assert diagnostic.field_path is not None
        assert _resolve(payload, diagnostic.field_path) is not _MISSING, diagnostic.field_path


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_failures_map_to_specific_codes_not_a_catch_all() -> None:
    with pytest.raises(ValidationError) as caught:
        Model.model_validate_json(json.dumps(_invalid_payload()))
    codes = {d.code for d in normalize_validation_error(caught.value, root=Model)}
    assert "CORE.DOMAIN.INVALID_FORMAT" in codes
    assert "CORE.DOMAIN.INVALID_TYPE" in codes
    assert "CORE.SCHEMA.UNCLASSIFIED" not in codes


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_an_unknown_variant_tag_reports_as_such() -> None:
    payload = _invalid_payload()
    payload["elements"][0]["detail"] = {"detail_family": "invented", "element_id": "BAD ID"}
    with pytest.raises(ValidationError) as caught:
        Model.model_validate_json(json.dumps(payload))
    codes = {d.code for d in normalize_validation_error(caught.value, root=Model)}
    assert "CORE.DOMAIN.INVALID_VARIANT" in codes


_MISSING = object()


def _resolve(document: Any, path: str) -> Any:
    """Walk `a.b[0].c` through plain parsed JSON, returning `_MISSING` if it does not exist."""
    current = document
    token = ""
    index_digits = ""
    reading_index = False
    for character in path + ".":
        if character == "[":
            if token:
                if not isinstance(current, dict) or token not in current:
                    return _MISSING
                current = current[token]
                token = ""
            reading_index = True
            continue
        if character == "]":
            if not isinstance(current, list) or int(index_digits) >= len(current):
                return _MISSING
            current = current[int(index_digits)]
            index_digits = ""
            reading_index = False
            continue
        if reading_index:
            index_digits += character
            continue
        if character == ".":
            if token:
                if not isinstance(current, dict) or token not in current:
                    return _MISSING
                current = current[token]
                token = ""
            continue
        token += character
    return current
