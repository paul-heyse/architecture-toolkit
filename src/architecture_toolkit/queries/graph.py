"""The release-derived graph, and the facade that is the only way to ask it anything.

CORE-22 through CORE-25 and DATA-16. Three decisions carry the weight.

**The graph is built from the query session, not beside it.** `build_graph` takes a
`ReleaseContext` and projects two tables out of the same DataFusion session the recipes run in. So
the M3 hard gate — "DataFusion and NetworkX read the same release" — is a property of there being
one session rather than an assertion about two code paths that happen to agree today. It also makes
CORE-23's "minimal traversal attributes only" the projection list rather than a convention: the
graph cannot carry a field the `SELECT` did not ask for.

**The rich records stay in the tables.** A node knows its kind and an edge knows its type and its
traversal context, and that is all. Anything else a caller needs is hydrated from the release, which
is what keeps the graph disposable: nothing is lost by throwing it away and rebuilding it.

**The raw `MultiDiGraph` never leaves.** `nx.freeze` is applied, but the CORE-25 tests show why it
is only a partial guard — attribute dictionaries stay mutable and a write through a filtered view
reaches the base graph. The real protection is that the handle is private and the attributes are
three strings nobody would want to mutate.
"""

from dataclasses import dataclass
from typing import Final

import pyarrow as pa
from datafusion import col

from architecture_toolkit.domain.identifiers import (
    ElementId,
    ModelId,
    RelationshipId,
    ReleaseId,
    SemanticDigest,
)
from architecture_toolkit.queries import _nx
from architecture_toolkit.queries.context import ReleaseContext
from architecture_toolkit.queries.errors import GraphError

__all__ = [
    "EDGE_COLUMNS",
    "NODE_COLUMNS",
    "ArchitectureGraph",
    "build_graph",
]

NODE_COLUMNS: Final[tuple[str, ...]] = ("element_id", "kind_id")
"""The canonical object ID and its kind. `core.md` permits "minimal traversal attributes only"."""

EDGE_COLUMNS: Final[tuple[str, ...]] = (
    "source_element_id",
    "target_element_id",
    "relationship_id",
    "relationship_type_id",
    "context_id",
)
"""Endpoints, the canonical relationship ID that becomes the edge key, its type, and the traversal
context a policy filters on. Exactly the three attributes `docs/plans/w5-query-graph.md` names —
object kind, relationship type, selected traversal context — plus the identities."""

KIND = "kind_id"
RELATIONSHIP_TYPE = "relationship_type_id"
CONTEXT = "context_id"


@dataclass(frozen=True, slots=True)
class ArchitectureGraph:
    """A frozen, release-identified graph with query methods and no general mutation API (CORE-24).

    The facade carries its own identity because a path result has to say which release produced it,
    and a graph that could not name its release would make that provenance a caller's problem.
    """

    release_id: ReleaseId
    model_id: ModelId
    model_digest: SemanticDigest
    _graph: _nx.Graph

    @property
    def order(self) -> int:
        """How many canonical objects the graph holds."""
        return len(_nx.node_ids(self._graph))

    @property
    def size(self) -> int:
        """How many canonical relationships the graph holds, parallel ones counted separately."""
        return len(_nx.edges(self._graph))

    def node_ids(self) -> tuple[ElementId, ...]:
        return _nx.node_ids(self._graph)

    def relationship_ids(self) -> tuple[RelationshipId, ...]:
        return tuple(key for _, _, key in _nx.edges(self._graph))

    def edges(self) -> tuple[_nx.Edge, ...]:
        return _nx.edges(self._graph)

    def kind_of(self, element_id: ElementId) -> str:
        """The kind of one object, or `GraphError` for an object this release does not hold."""
        try:
            return str(_nx.node_attributes(self._graph, element_id)[KIND])
        except KeyError:
            message = f"{element_id!r} is not in release {self.release_id}"
            raise GraphError(message) from None

    def type_of(self, edge: _nx.Edge) -> str:
        return str(_nx.edge_attributes(self._graph, edge)[RELATIONSHIP_TYPE])

    def context_of(self, edge: _nx.Edge) -> str | None:
        return _nx.edge_attributes(self._graph, edge)[CONTEXT]

    def relationships_between(
        self, source: ElementId, target: ElementId
    ) -> tuple[RelationshipId, ...]:
        """Every relationship joining this pair — plural, because CORE-23 keeps parallel ones."""
        return _nx.edge_keys_between(self._graph, source, target)

    def is_frozen(self) -> bool:
        """CORE-25. True, and `tests/unit/test_graph_facade.py` says why that is not enough."""
        return _nx.is_frozen(self._graph)


def build_graph(context: ReleaseContext) -> ArchitectureGraph:
    """Project one release into a disposable graph (CORE-22, CORE-23, DATA-16)."""
    nodes = context.table("elements").select(*(col(name) for name in NODE_COLUMNS))
    relationships = context.table("relationships").select(*(col(name) for name in EDGE_COLUMNS))
    return _assemble(context, nodes.to_arrow_table(), relationships.to_arrow_table())


def _assemble(
    context: ReleaseContext, nodes: pa.Table, relationships: pa.Table
) -> ArchitectureGraph:
    element_ids = {str(row["element_id"]) for row in nodes.to_pylist()}
    graph = _nx.build(
        {"release_id": context.scope.release_id, "model_id": context.scope.model_id},
        ((str(row["element_id"]), {KIND: str(row[KIND])}) for row in nodes.to_pylist()),
        (
            (
                str(row["source_element_id"]),
                str(row["target_element_id"]),
                str(row["relationship_id"]),
                {RELATIONSHIP_TYPE: str(row[RELATIONSHIP_TYPE]), CONTEXT: _optional(row[CONTEXT])},
            )
            for row in relationships.to_pylist()
        ),
    )
    invented = sorted(set(_nx.node_ids(graph)) - element_ids)
    if invented:
        message = (
            f"release {context.scope.release_id} has relationship endpoints that are not elements: "
            f"{invented}"
        )
        raise GraphError(message)
    return ArchitectureGraph(
        release_id=context.scope.release_id,
        model_id=context.scope.model_id,
        model_digest=context.scope.model_digest,
        _graph=_nx.freeze(graph),
    )


def _optional(value: object) -> str | None:
    return None if value is None else str(value)
