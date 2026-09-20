"""Resolve diagnostics to source locations (CORE-19).

`ARCH-TOOL-CORE-001` §5E fixes the order: exact canonical ID and field path; the semantic
(Pydantic) path; the nearest parent record; the document. Every located diagnostic says which of
those it got, as `location_resolution` in its context, so a fallback reads as a fallback rather
than as a position somebody should trust.

Two path grammars arrive here. Pydantic errors carry a location tuple that
`normalize.semantic_segments` turns into the index grammar the SourceMap is keyed by. Cross-record
rules carry `field_path` in the identity grammar (`elements.schema-1.detail.fields.submitted_by`),
which the SourceMap indexes from the same walk; identifiers may contain dots, so that grammar is
never tokenized inside an identity — the record is found by lookup and only the suffix after it is
stripped segment by segment.

Locating derives a new record through `model_validate`, never `model_copy(update=)`, and leaves
`diagnostic_id` alone: a location is where a finding was seen, not what it is.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ValidationError

from architecture_toolkit.domain.source import (
    LocationResolution,
    SourceEntry,
    SourceLocation,
    SourceMap,
)
from architecture_toolkit.validation.claims import ValidationClaimReport
from architecture_toolkit.validation.diagnostics import Diagnostic
from architecture_toolkit.validation.normalize import (
    normalize_validation_error,
    semantic_segments,
)

__all__ = ["locate_diagnostic", "locate_report", "locate_validation_error"]

_RESOLUTION = "location_resolution"


def _with_location(
    diagnostic: Diagnostic,
    location: SourceLocation,
    resolution: LocationResolution,
    source_map: SourceMap,
) -> Diagnostic:
    placed = location.model_validate(dict(location) | {"document_id": source_map.document_id})
    context = tuple(
        sorted(
            (
                *(pair for pair in diagnostic.context if pair[0] != _RESOLUTION),
                (_RESOLUTION, resolution.value),
            )
        )
    )
    return diagnostic.model_validate(
        dict(diagnostic) | {"source_location": placed, "context": context}
    )


def locate_validation_error(
    error: ValidationError, *, root: type[BaseModel], source_map: SourceMap
) -> tuple[Diagnostic, ...]:
    """Normalize and locate every error; `path` when the full location is mapped."""
    located: list[Diagnostic] = []
    raw_errors = error.errors(include_url=False)
    diagnostics = normalize_validation_error(error, root=root)
    for diagnostic, raw in zip(diagnostics, raw_errors, strict=True):
        segments: Sequence[str | int] = semantic_segments(root, tuple(raw.get("loc", ())))
        entry, matched = source_map.nearest(segments)
        if entry is None:
            located.append(
                _with_location(diagnostic, source_map.root, LocationResolution.DOCUMENT, source_map)
            )
            continue
        if matched == 0:
            resolution = LocationResolution.DOCUMENT
        elif matched == len(segments):
            resolution = LocationResolution.PATH
        else:
            resolution = LocationResolution.PARENT
        location = entry.value
        # An unknown field is best pointed at by the key the author typed.
        if resolution is LocationResolution.PATH and raw.get("type") == "extra_forbidden":
            location = entry.key or entry.value
        located.append(_with_location(diagnostic, location, resolution, source_map))
    return tuple(located)


def _anchor_path(diagnostic: Diagnostic, source_map: SourceMap) -> str | None:
    """The identity-grammar path of the record the diagnostic addresses, if it names one."""
    if diagnostic.relationship_id is not None:
        for path in source_map.record_paths.get(diagnostic.relationship_id, ()):
            if path.startswith("relationships."):
                return path
    if diagnostic.canonical_object_id is not None:
        paths = source_map.record_paths.get(diagnostic.canonical_object_id, ())
        if paths:
            return paths[0]
    return None


def _entry(source_map: SourceMap, path: str) -> SourceEntry | None:
    return source_map.lookup_identity(path) or source_map.lookup(path)


def locate_diagnostic(diagnostic: Diagnostic, source_map: SourceMap) -> Diagnostic:
    """The rule route: identity anchor, then field path, then parent, then document."""
    if diagnostic.source_location is not None:
        return diagnostic
    anchor = _anchor_path(diagnostic, source_map)
    path = diagnostic.field_path

    if path:
        exact = _entry(source_map, path)
        if exact is not None:
            return _with_location(diagnostic, exact.value, LocationResolution.EXACT, source_map)
        # Strip the suffix one segment at a time, never inside the record identity.
        under_anchor = anchor is not None and (path == anchor or path.startswith(anchor + "."))
        base = anchor if under_anchor else ""
        suffix = path[len(base) :].lstrip(".") if base else path
        parts = suffix.split(".") if suffix else []
        while parts:
            parts.pop()
            candidate = ".".join(([base] if base else []) + parts)
            if not candidate:
                break
            nearer = _entry(source_map, candidate)
            if nearer is not None:
                return _with_location(
                    diagnostic, nearer.value, LocationResolution.PARENT, source_map
                )

    if anchor is not None:
        record = source_map.lookup_identity(anchor)
        if record is not None:
            resolution = LocationResolution.PARENT if path else LocationResolution.EXACT
            return _with_location(diagnostic, record.value, resolution, source_map)

    return _with_location(diagnostic, source_map.root, LocationResolution.DOCUMENT, source_map)


def locate_report(report: ValidationClaimReport, source_map: SourceMap) -> ValidationClaimReport:
    """The same report, every diagnostic located. Claims and identities are untouched."""
    located = tuple(locate_diagnostic(diagnostic, source_map) for diagnostic in report.diagnostics)
    return report.model_validate(dict(report) | {"diagnostics": located})
