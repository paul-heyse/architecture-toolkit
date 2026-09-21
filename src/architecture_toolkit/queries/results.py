"""What a graph query returns, and the one thing it is not allowed to say (CORE-28, DATA-17).

> Implement named traversal policies and retain paths, versions and evidence; **do not equate
> reachability with certain failure.**
> — DATA-17

Two design consequences follow, and both are in the types rather than in a warning.

**No result discards the path that justifies it.** `GraphPathResult` carries the ordered node IDs
*and* the ordered relationship IDs, so "these seven things are potentially affected" can always be
answered with "through which relationships". A result type that carried only endpoints would make
that impossible to add later without changing every caller.

**The vocabulary cannot assert certainty.** `PathClassification` is closed and says only what was
traversed. There is deliberately no member meaning "will fail" or "is broken", and
`tests/unit/test_result_vocabulary.py` asserts that no member ever acquires one — a policy-only
guard for DATA-17, because the requirement is about what the toolkit is permitted to claim.

**A truncated answer says so.** CORE-29's caps are enforced before materialization, which means a
result can be partial. `TraversalResult.truncated` and `limit_reached` are how a caller finds out;
a silently capped answer that looked complete would be a worse failure than a slow query.
"""

from enum import StrEnum

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    ElementId,
    PolicyId,
    RelationshipId,
    RelationshipTypeId,
    ReleaseId,
    SchemaVersion,
)

__all__ = ["GraphPathResult", "PathClassification", "TraversalResult"]


class PathClassification(StrEnum):
    """What a path means. Every member states a traversal; none states a consequence."""

    POTENTIALLY_AFFECTED = "potentially_affected"
    """Reachable through the policy's relationships. A statement about the model, not a
    prediction about behaviour."""

    TRACED = "traced"
    """Connected by an explicit modelling relationship — a requirement and what realizes it."""

    CONTAINED_BY = "contained_by"
    """Inside the structural hierarchy of the start object."""


class GraphPathResult(CompiledRecord):
    """One explainable path, with the provenance that makes it re-derivable (CORE-28)."""

    release_id: ReleaseId
    policy_id: PolicyId
    policy_version: SchemaVersion
    start: ElementId
    end: ElementId
    node_ids: tuple[ElementId, ...]
    relationship_ids: tuple[RelationshipId, ...]
    relationship_types: tuple[RelationshipTypeId, ...]
    depth: int
    classification: PathClassification


class TraversalResult(CompiledRecord):
    """Every path one traversal found, and whether a cap stopped it finding more."""

    release_id: ReleaseId
    policy_id: PolicyId
    policy_version: SchemaVersion
    start: ElementId
    classification: PathClassification
    paths: tuple[GraphPathResult, ...] = ()
    truncated: bool = False
    limit_reached: str | None = None
    """Which cap stopped the traversal — `max_paths`, `max_results` or `None`.

    Naming the cap rather than reporting a bare flag is what lets a caller decide whether to raise
    it: "there were more than two hundred paths" and "there were more than a hundred affected
    objects" are different situations with different answers."""

    @property
    def reached(self) -> tuple[ElementId, ...]:
        """The distinct objects the traversal reached, in first-seen order."""
        seen: dict[ElementId, None] = {}
        for path in self.paths:
            seen.setdefault(path.end, None)
        return tuple(seen)
