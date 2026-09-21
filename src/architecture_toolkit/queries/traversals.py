"""The named traversals DATA-17 asks for, each declaring what it follows and where it stops.

> Implement named traversal policies and retain paths, versions and evidence.
> — DATA-17

Each is a thin function over one policy, and the thinness is the point: the declaration lives in
`queries/policy.py`, where it is versioned and checked against the profile, and these are the names
a caller reaches for. A function that built its own filter would be a second, unversioned policy.

`find_unverified_dependencies` is the one that is not purely a graph question, and it shows the
split the wave is built on: the traversal says *what is reachable*, and the release's own tables say
*what is known about it*. Both come from the same session, so the two halves cannot describe
different releases.

`find_containment_cycles` is the other name DATA-17
lists; they are structural analyses rather than traversals and live in `queries/algorithms.py`.
"""

from collections.abc import Iterable

from architecture_toolkit.domain.identifiers import ElementId
from architecture_toolkit.domain.status import GapState, TechnicalQualification
from architecture_toolkit.queries.context import ReleaseContext
from architecture_toolkit.queries.graph import ArchitectureGraph
from architecture_toolkit.queries.policy import policy_for
from architecture_toolkit.queries.results import TraversalResult

__all__ = [
    "UNVERIFIED_QUALIFICATIONS",
    "find_interface_dependents",
    "find_unverified_dependencies",
    "trace_requirement_implementation",
]

UNVERIFIED_QUALIFICATIONS: frozenset[str] = frozenset(
    {
        TechnicalQualification.NOT_QUALIFIED.value,
        GapState.UNKNOWN.value,
        GapState.EVIDENCE_GAP.value,
    }
)
"""What counts as not yet verified.

`QUALIFICATION_FAILED` is deliberately absent: something that failed qualification *was* verified,
and the answer to "what have we not checked" is not the same as "what did not work".
`NOT_APPLICABLE` and `WITHHELD` are absent for the same reason — DATA-41 asks these to stay
distinct rather than collapse into one word for absence."""


def trace_requirement_implementation(
    graph: ArchitectureGraph, requirement_id: ElementId
) -> TraversalResult:
    """What realizes this requirement, and through which relationships (DATA-17)."""
    return graph.traverse(policy_for("trace.requirement_implementation"), requirement_id)


def find_interface_dependents(graph: ArchitectureGraph, interface_id: ElementId) -> TraversalResult:
    """What would have to change if this interface changed (DATA-17).

    The classification is `potentially_affected`, never a claim that anything will break.
    """
    return graph.traverse(policy_for("dependents.interface"), interface_id)


def find_unverified_dependencies(
    graph: ArchitectureGraph, context: ReleaseContext, element_id: ElementId
) -> TraversalResult:
    """Dependencies whose technical qualification has not been established (DATA-17).

    Two halves from one session: the traversal says what this object depends on, and the release's
    `elements` table says what is recorded about each of those. Filtering afterwards rather than
    inside the traversal keeps the policy about relationships and the status question about status
    — and keeps the paths, so the answer can still say *how* an unverified dependency is reached.
    """
    reachable = graph.traverse(policy_for("dependencies.direct"), element_id)
    unverified = _unverified(context, reachable.reached)
    return reachable.model_validate(
        dict(reachable)
        | {"paths": tuple(path for path in reachable.paths if path.end in unverified)}
    )


def _unverified(context: ReleaseContext, element_ids: Iterable[ElementId]) -> frozenset[ElementId]:
    candidates = list(element_ids)
    if not candidates:
        return frozenset()
    rows = context.arrow(
        "SELECT element_id FROM elements "
        "WHERE array_has($candidates, element_id) "
        "AND array_has($qualifications, status['technical_qualification'])",
        {
            "candidates": candidates,
            "qualifications": sorted(UNVERIFIED_QUALIFICATIONS),
        },
    ).to_pylist()
    return frozenset(str(row["element_id"]) for row in rows)
