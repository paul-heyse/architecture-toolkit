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

__all__ = [
    "ComponentResult",
    "CondensationResult",
    "CycleResult",
    "GraphPathResult",
    "PathClassification",
    "ReachabilityEdge",
    "ReductionEdge",
    "ReleaseComparison",
    "TraversalResult",
]


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


class CycleResult(CompiledRecord):
    """One cycle, with the relationships that realize it (CORE-30).

    `nx.simple_cycles` reports a multigraph cycle as a sequence of nodes and keeps no keys, so a
    cycle closed by one of two parallel relationships is indistinguishable from one closed by the
    other. `queries/algorithms.py` recovers the keys, and where a step has several relationships it
    reports each realization rather than choosing one — the same promise CORE-23 makes about paths.
    """

    release_id: ReleaseId
    policy_id: PolicyId
    policy_version: SchemaVersion
    node_ids: tuple[ElementId, ...]
    relationship_ids: tuple[RelationshipId, ...]
    length: int


class ComponentResult(CompiledRecord):
    """One strongly connected component, mapped back to canonical IDs (CORE-30)."""

    release_id: ReleaseId
    policy_id: PolicyId
    policy_version: SchemaVersion
    element_ids: tuple[ElementId, ...]
    is_cyclic: bool
    """A component of one element is only cyclic if that element relates to itself."""


class CondensationResult(CompiledRecord):
    """The component DAG: every SCC collapsed to a node, and the edges between them (CORE-30)."""

    release_id: ReleaseId
    policy_id: PolicyId
    policy_version: SchemaVersion
    components: tuple[ComponentResult, ...]
    edges: tuple[tuple[int, int], ...]
    """Indices into `components`, which is how NetworkX reports a condensation and the only honest
    way to express it: a condensation edge joins two *sets* of objects and is not a relationship."""


class ReachabilityEdge(CompiledRecord):
    """A transitive-closure edge: `source` reaches `target` somehow (CORE-31).

    **It carries no relationship IDs, deliberately.** `nx.transitive_closure` mints its derived
    edges with the integer key `0`, in the same key space as a canonical relationship ID, and a
    field to put that in would be a field somebody eventually treats as a relationship. Derived
    analysis never replaces canonical relationships, and here that is enforced by the absence of
    the field rather than by a warning.
    """

    source: ElementId
    target: ElementId


class ReductionEdge(CompiledRecord):
    """A transitive-reduction edge, with every relationship that realizes it (CORE-31).

    Unlike a closure edge this one *is* backed by relationships — `nx.transitive_reduction` returns
    a `DiGraph` and drops the keys, so they are recovered here. Plural, because two parallel
    relationships both realize the step and picking one would misreport the model.
    """

    source: ElementId
    target: ElementId
    relationship_ids: tuple[RelationshipId, ...]


class ReleaseComparison(CompiledRecord):
    """What changed between two releases, at graph identity (DATA-17).

    Deliberately about identities rather than content: `semantic_delta` in `domain/semantics.py`
    answers "what changed in this model" and W6 owns the change narrative. This answers the
    narrower question a graph can answer — which objects and relationships exist on each side.
    """

    base_release_id: ReleaseId
    candidate_release_id: ReleaseId
    added_elements: tuple[ElementId, ...] = ()
    removed_elements: tuple[ElementId, ...] = ()
    added_relationships: tuple[RelationshipId, ...] = ()
    removed_relationships: tuple[RelationshipId, ...] = ()
    retyped_relationships: tuple[
        tuple[RelationshipId, RelationshipTypeId, RelationshipTypeId], ...
    ] = ()
    """`(relationship_id, base_type, candidate_type)` for a relationship whose type changed while
    keeping its identity — the one change a bare set difference would report as nothing at all."""

    @property
    def is_empty(self) -> bool:
        return not (
            self.added_elements
            or self.removed_elements
            or self.added_relationships
            or self.removed_relationships
            or self.retyped_relationships
        )
