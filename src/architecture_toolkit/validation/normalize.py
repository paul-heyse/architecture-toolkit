"""Normalize Pydantic validation failures into stable diagnostics (CORE-11).

Two properties make this more than a lookup table.

**The map is total over `pydantic_core.ErrorType`.** That type is a `Literal` with 104 members,
enumerable at runtime, so `tests/unit/test_normalize.py` asserts the mapping covers exactly those
104 in both directions. A Pydantic upgrade that adds an error type then fails a test rather than
falling through to a generic code and quietly degrading every report that depends on it.

**The field path is walked, not string-joined.** For a *matched* discriminated variant Pydantic
inserts the tag into the error location: validating `{"detail": {"detail_family": "interface",
"timeout_ms": "no"}}` yields `('detail', 'interface', 'timeout_ms')`. Emitting that verbatim
would produce `detail.interface.timeout_ms`, a path that does not exist in the source document.
Dropping any segment matching a known tag would be worse — it would mangle a legitimate field
named `interface`. So the walk descends the annotations alongside the location and drops a
segment only where the annotation at that point really is a discriminated union.
"""

from collections.abc import Mapping, Sequence
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

from architecture_toolkit.domain.authoring.errors import AuthoringError
from architecture_toolkit.domain.source import LocationResolution, render_segments
from architecture_toolkit.validation.codes import CODES
from architecture_toolkit.validation.diagnostics import Diagnostic, build_diagnostic

__all__ = [
    "ERROR_TYPE_CODES",
    "field_path",
    "normalize_authoring_error",
    "normalize_validation_error",
    "semantic_segments",
]

# Keyed by `str`, not by `pydantic_core.ErrorType`. The value arriving from `errors()` is an
# ordinary string, and annotating the key as the `Literal` would force a cast at the one place
# the lookup happens. Totality against those 104 members is asserted in
# `tests/unit/test_normalize.py` instead, where it is a property that can actually fail.
ERROR_TYPE_CODES: Mapping[str, str] = {
    # an absent required input
    "missing": "CORE.DOMAIN.MISSING_REQUIRED_FIELD",
    "missing_argument": "CORE.DOMAIN.MISSING_REQUIRED_FIELD",
    "missing_keyword_only_argument": "CORE.DOMAIN.MISSING_REQUIRED_FIELD",
    "missing_positional_only_argument": "CORE.DOMAIN.MISSING_REQUIRED_FIELD",
    "missing_sentinel_error": "CORE.DOMAIN.MISSING_REQUIRED_FIELD",
    # an input the closed record does not declare
    "extra_forbidden": "CORE.DOMAIN.UNKNOWN_FIELD",
    "multiple_argument_values": "CORE.DOMAIN.UNKNOWN_FIELD",
    "no_such_attribute": "CORE.DOMAIN.UNKNOWN_FIELD",
    "unexpected_keyword_argument": "CORE.DOMAIN.UNKNOWN_FIELD",
    "unexpected_positional_argument": "CORE.DOMAIN.UNKNOWN_FIELD",
    # a discriminated-union tag that names nothing
    "union_tag_invalid": "CORE.DOMAIN.INVALID_VARIANT",
    "union_tag_not_found": "CORE.DOMAIN.INVALID_VARIANT",
    # the wrong type under strict validation
    "arguments_type": "CORE.DOMAIN.INVALID_TYPE",
    "bool_type": "CORE.DOMAIN.INVALID_TYPE",
    "bytes_type": "CORE.DOMAIN.INVALID_TYPE",
    "callable_type": "CORE.DOMAIN.INVALID_TYPE",
    "complex_type": "CORE.DOMAIN.INVALID_TYPE",
    "dataclass_exact_type": "CORE.DOMAIN.INVALID_TYPE",
    "dataclass_type": "CORE.DOMAIN.INVALID_TYPE",
    "date_type": "CORE.DOMAIN.INVALID_TYPE",
    "datetime_type": "CORE.DOMAIN.INVALID_TYPE",
    "decimal_type": "CORE.DOMAIN.INVALID_TYPE",
    "dict_type": "CORE.DOMAIN.INVALID_TYPE",
    "float_type": "CORE.DOMAIN.INVALID_TYPE",
    "frozen_set_type": "CORE.DOMAIN.INVALID_TYPE",
    "int_type": "CORE.DOMAIN.INVALID_TYPE",
    "is_instance_of": "CORE.DOMAIN.INVALID_TYPE",
    "is_subclass_of": "CORE.DOMAIN.INVALID_TYPE",
    "iterable_type": "CORE.DOMAIN.INVALID_TYPE",
    "json_type": "CORE.DOMAIN.INVALID_TYPE",
    "list_type": "CORE.DOMAIN.INVALID_TYPE",
    "mapping_type": "CORE.DOMAIN.INVALID_TYPE",
    "model_attributes_type": "CORE.DOMAIN.INVALID_TYPE",
    "model_type": "CORE.DOMAIN.INVALID_TYPE",
    "set_type": "CORE.DOMAIN.INVALID_TYPE",
    "string_sub_type": "CORE.DOMAIN.INVALID_TYPE",
    "string_type": "CORE.DOMAIN.INVALID_TYPE",
    "time_delta_type": "CORE.DOMAIN.INVALID_TYPE",
    "time_type": "CORE.DOMAIN.INVALID_TYPE",
    "tuple_type": "CORE.DOMAIN.INVALID_TYPE",
    "url_type": "CORE.DOMAIN.INVALID_TYPE",
    "uuid_type": "CORE.DOMAIN.INVALID_TYPE",
    # right type, unparseable or misformatted value
    "bool_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "bytes_invalid_encoding": "CORE.DOMAIN.INVALID_FORMAT",
    "complex_str_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "date_from_datetime_inexact": "CORE.DOMAIN.INVALID_FORMAT",
    "date_from_datetime_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "date_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "datetime_from_date_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "datetime_object_invalid": "CORE.DOMAIN.INVALID_FORMAT",
    "datetime_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "decimal_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "float_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "int_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "int_parsing_size": "CORE.DOMAIN.INVALID_FORMAT",
    "string_not_ascii": "CORE.DOMAIN.INVALID_FORMAT",
    "string_pattern_mismatch": "CORE.DOMAIN.INVALID_FORMAT",
    "string_unicode": "CORE.DOMAIN.INVALID_FORMAT",
    "time_delta_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "time_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "url_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "url_scheme": "CORE.DOMAIN.INVALID_FORMAT",
    "url_syntax_violation": "CORE.DOMAIN.INVALID_FORMAT",
    "uuid_parsing": "CORE.DOMAIN.INVALID_FORMAT",
    "uuid_version": "CORE.DOMAIN.INVALID_FORMAT",
    # well-formed but outside the permitted range or vocabulary
    "bytes_too_long": "CORE.DOMAIN.INVALID_VALUE",
    "bytes_too_short": "CORE.DOMAIN.INVALID_VALUE",
    "date_future": "CORE.DOMAIN.INVALID_VALUE",
    "date_past": "CORE.DOMAIN.INVALID_VALUE",
    "datetime_future": "CORE.DOMAIN.INVALID_VALUE",
    "datetime_past": "CORE.DOMAIN.INVALID_VALUE",
    "decimal_max_digits": "CORE.DOMAIN.INVALID_VALUE",
    "decimal_max_places": "CORE.DOMAIN.INVALID_VALUE",
    "decimal_whole_digits": "CORE.DOMAIN.INVALID_VALUE",
    "enum": "CORE.DOMAIN.INVALID_VALUE",
    "finite_number": "CORE.DOMAIN.INVALID_VALUE",
    "greater_than": "CORE.DOMAIN.INVALID_VALUE",
    "greater_than_equal": "CORE.DOMAIN.INVALID_VALUE",
    "int_from_float": "CORE.DOMAIN.INVALID_VALUE",
    "json_invalid": "CORE.DOMAIN.INVALID_VALUE",
    "less_than": "CORE.DOMAIN.INVALID_VALUE",
    "less_than_equal": "CORE.DOMAIN.INVALID_VALUE",
    "literal_error": "CORE.DOMAIN.INVALID_VALUE",
    "multiple_of": "CORE.DOMAIN.INVALID_VALUE",
    "none_required": "CORE.DOMAIN.INVALID_VALUE",
    "string_too_long": "CORE.DOMAIN.INVALID_VALUE",
    "string_too_short": "CORE.DOMAIN.INVALID_VALUE",
    "timezone_aware": "CORE.DOMAIN.INVALID_VALUE",
    "timezone_naive": "CORE.DOMAIN.INVALID_VALUE",
    "timezone_offset": "CORE.DOMAIN.INVALID_VALUE",
    "too_long": "CORE.DOMAIN.INVALID_VALUE",
    "too_short": "CORE.DOMAIN.INVALID_VALUE",
    "url_too_long": "CORE.DOMAIN.INVALID_VALUE",
    # a write to a frozen record
    "frozen_field": "CORE.DOMAIN.MUTUALLY_EXCLUSIVE_FIELDS",
    "frozen_instance": "CORE.DOMAIN.MUTUALLY_EXCLUSIVE_FIELDS",
    # a toolkit defect surfacing through pydantic, not a model defect
    "default_factory_not_called": "CORE.SCHEMA.RULE_CRASHED",
    "get_attribute_error": "CORE.SCHEMA.RULE_CRASHED",
    "invalid_key": "CORE.SCHEMA.RULE_CRASHED",
    "iteration_error": "CORE.SCHEMA.RULE_CRASHED",
    "needs_python_object": "CORE.SCHEMA.RULE_CRASHED",
    "recursion_loop": "CORE.SCHEMA.RULE_CRASHED",
    "set_item_not_hashable": "CORE.SCHEMA.RULE_CRASHED",
    # a custom validator error carrying no registered code
    "assertion_error": "CORE.SCHEMA.UNCLASSIFIED",
    "value_error": "CORE.SCHEMA.UNCLASSIFIED",
}


def _strip_optional(annotation: Any) -> Any:
    """Remove a `| None` arm, leaving the single meaningful arm if there is one.

    Needed before looking for a discriminator: an optional tagged union is represented as
    `Optional[Annotated[A | B, FieldInfo(discriminator=...)]]`, so the `Annotated` that carries
    the tag is one level in rather than at the top.
    """
    if get_origin(annotation) in {Union, UnionType}:
        arms = [arm for arm in get_args(annotation) if arm is not type(None)]
        if len(arms) == 1:
            return arms[0]
    return annotation


def _discriminator(annotation: Any) -> tuple[str | None, tuple[Any, ...]]:
    """The discriminator field and variants of an annotation, if it is a tagged union."""
    candidate = _strip_optional(annotation)
    if get_origin(candidate) is Annotated:
        inner, *metadata = get_args(candidate)
        for item in metadata:
            name = getattr(item, "discriminator", None)
            if isinstance(name, str):
                return name, get_args(inner)
    return None, ()


def _unwrap(annotation: Any) -> Any:
    """Strip `Annotated` and an optional `None` arm, leaving the meaningful annotation."""
    candidate = _strip_optional(annotation)
    if get_origin(candidate) is Annotated:
        return get_args(candidate)[0]
    return candidate


def _tag_values(variant: Any, discriminator: str) -> set[str]:
    field = getattr(variant, "model_fields", {}).get(discriminator)
    if field is None:
        return set()
    return {str(value) for value in get_args(_unwrap(field.annotation))}


def _sequence_item(annotation: Any) -> Any:
    args = get_args(annotation)
    return args[0] if args else None


def semantic_segments(
    root: type[BaseModel] | None, loc: Sequence[str | int]
) -> tuple[str | int, ...]:
    """The document path of a Pydantic error location, with injected union tags dropped.

    `root` may be `None` when the model type is unknown; the walk then degrades to a plain copy,
    which is still better than nothing and is never silently wrong about a tag, because without
    annotations it drops no segment at all.
    """
    segments: list[str | int] = []
    current: Any = root
    for segment in loc:
        if isinstance(segment, int):
            segments.append(segment)
            current = _sequence_item(_unwrap(current)) if current is not None else None
            continue
        discriminator, variants = _discriminator(current)
        if discriminator is not None:
            matched = [v for v in variants if segment in _tag_values(v, discriminator)]
            if matched:
                # The injected tag. Not a field of the document; skip it and descend.
                current = matched[0]
                continue
        segments.append(segment)
        fields = getattr(_unwrap(current), "model_fields", None) if current is not None else None
        field = fields.get(segment) if isinstance(fields, dict) else None
        current = field.annotation if field is not None else None
    return tuple(segments)


def field_path(root: type[BaseModel] | None, loc: Sequence[str | int]) -> str | None:
    """Render a Pydantic error location as a path into the authored document."""
    if not loc:
        return None
    return render_segments(semantic_segments(root, loc)) or None


def _context(error: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Bounded, JSON-safe context. The input is rendered, never carried by reference."""
    items: list[tuple[str, str]] = [("error_type", str(error.get("type", "")))]
    raw = error.get("ctx")
    if isinstance(raw, dict):
        items += [(str(key), str(value)[:120]) for key, value in raw.items()]
    if "input" in error:
        items.append(("input", repr(error["input"])[:120]))
    return tuple(sorted(items))


def normalize_validation_error(
    error: ValidationError,
    *,
    root: type[BaseModel] | None = None,
    canonical_object_id: str | None = None,
) -> tuple[Diagnostic, ...]:
    """One diagnostic per underlying error, with a registered code and a resolvable path.

    `include_url=False` on purpose: the URL Pydantic appends is version-coupled, and carrying it
    into a stored diagnostic would make a library upgrade look like a change in the finding.
    """
    produced: list[Diagnostic] = []
    for raw in error.errors(include_url=False):
        error_type = str(raw.get("type", ""))
        # A validator that raised `PydanticCustomError` with a registered code keeps it. That is
        # the bridge from record-local rules into this namespace, and it means the 104-entry
        # table only has to cover Pydantic's own built-ins.
        code = (
            error_type
            if error_type in CODES
            else ERROR_TYPE_CODES.get(
                error_type,  # type: ignore[arg-type]
                "CORE.SCHEMA.UNCLASSIFIED",
            )
        )
        produced.append(
            build_diagnostic(
                code,
                message=str(raw.get("msg", "validation failed")),
                canonical_object_id=canonical_object_id,
                field_path=field_path(root, raw.get("loc", ())),
                context=_context(raw),
            )
        )
    return tuple(produced)


def normalize_authoring_error(error: AuthoringError) -> tuple[Diagnostic, ...]:
    """One diagnostic per finding — the raised error and every related one, in stream order.

    The location is exact by construction: the adapter reports the mark of the construct
    itself, so `location_resolution` says so and the renderer prints `file:line:column`.
    """
    return tuple(
        build_diagnostic(
            finding.code,
            message=finding.message,
            field_path=finding.location.semantic_path or None,
            context=(
                *finding.context,
                ("location_resolution", LocationResolution.EXACT.value),
            ),
            source_location=finding.location,
        )
        for finding in error
    )
