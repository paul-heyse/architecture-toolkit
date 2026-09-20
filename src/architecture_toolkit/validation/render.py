"""Human and machine renderings of a validation result (CORE-11, CORE-19).

The four-line form is specified in `ARCH-TOOL-CORE-001` §5E and repeated in the W2 plan:

    path/to/model.yaml:87:11
    ERROR CORE.RELATION.UNRESOLVED_ENDPOINT
    elements[4].relationships[2].target_element_id
    "software.system.missing" does not resolve.

Without a source map `source_location` is `None` and line one degrades to the bare path with no
`:line:column`. That degradation is specified rather than improvised: emitting `:0:0` would teach
every downstream reader to accept a position that means "unknown". When W2's resolution chain
fell back to a parent record or to the document, line one says so — `(nearest: <path>)` — so a
reader never mistakes the nearest mapped position for the exact one.

Rendering lives here rather than in the CLI so it can be tested without argparse, and so the
portal later produces the same bytes.
"""

from collections.abc import Iterable

from architecture_toolkit.validation.claims import ValidationClaimReport
from architecture_toolkit.validation.diagnostics import Diagnostic

__all__ = ["render_diagnostics", "render_report"]


def _location(diagnostic: Diagnostic, source: str) -> str:
    where = diagnostic.source_location
    if where is None or where.line is None:
        return source
    position = (
        f"{source}:{where.line}"
        if where.column is None
        else (f"{source}:{where.line}:{where.column}")
    )
    resolution = dict(diagnostic.context).get("location_resolution")
    if resolution in {"parent", "document"}:
        return f"{position} (nearest: {where.semantic_path or '(document)'})"
    return position


def render_diagnostics(diagnostics: Iterable[Diagnostic], *, source: str) -> str:
    blocks = [
        "\n".join(
            (
                _location(diagnostic, source),
                f"{diagnostic.severity.value.upper()} {diagnostic.code}",
                diagnostic.field_path or diagnostic.canonical_object_id or "(model)",
                diagnostic.message,
            )
        )
        for diagnostic in diagnostics
    ]
    return "\n\n".join(blocks)


def render_report(report: ValidationClaimReport, *, source: str) -> str:
    """Diagnostics, then one line per claim. The claim block is the honest part."""
    sections: list[str] = []
    if report.diagnostics:
        sections.append(render_diagnostics(report.diagnostics, source=source))
    width = max(len(outcome.claim.value) for outcome in report.claims)
    status_width = max(len(outcome.status.value) for outcome in report.claims)
    sections.append(
        "\n".join(
            f"{outcome.claim.value:<{width}}  {outcome.status.value:<{status_width}}  "
            f"{outcome.scope}"
            for outcome in report.claims
        )
    )
    return "\n\n".join(sections)
