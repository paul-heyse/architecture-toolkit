"""What the facade exposes, and what it deliberately does not (CORE-23, CORE-24, CORE-25)."""

import pytest

from architecture_toolkit.queries import _nx
from architecture_toolkit.queries.errors import GraphError
from architecture_toolkit.queries.graph import (
    EDGE_COLUMNS,
    NODE_COLUMNS,
    ArchitectureGraph,
)

READ_ONLY_SURFACE = frozenset(
    {
        "release_id",
        "model_id",
        "model_digest",
        "order",
        "size",
        "node_ids",
        "relationship_ids",
        "edges",
        "kind_of",
        "type_of",
        "context_of",
        "relationships_between",
        "is_frozen",
    }
)
"""Every public name on the facade. CORE-24 says there is no general mutation API; this is the
list that says so, and the test below fails if a method is added without being classified."""

TRAVERSAL_ATTRIBUTES = frozenset({"kind_id", "relationship_type_id", "context_id"})
"""The three `core.md` permits: object kind, relationship type, selected traversal context."""


def sample() -> ArchitectureGraph:
    graph = _nx.build(
        {"release_id": "rel-0001"},
        (("a", {"kind_id": "software.system"}), ("b", {"kind_id": "software.component"})),
        (
            ("a", "b", "rel-1", {"relationship_type_id": "contains", "context_id": None}),
            ("a", "b", "rel-2", {"relationship_type_id": "depends_on", "context_id": "ctx-1"}),
        ),
    )
    return ArchitectureGraph(
        release_id="rel-0001",
        model_id="sample-service",
        model_digest="sha256:" + "0" * 64,
        _graph=_nx.freeze(graph),
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-24")
def test_the_facade_exposes_no_mutation_api() -> None:
    """A method added without a decision fails here rather than shipping a way to edit a release."""
    public = {name for name in dir(ArchitectureGraph) if not name.startswith("_")}

    assert public == READ_ONLY_SURFACE


@pytest.mark.unit
@pytest.mark.requirement("CORE-23")
def test_the_graph_carries_only_the_attributes_the_contract_permits() -> None:
    """Minimal attributes as the projection list, not as a convention (`core.md § NetworkX`).

    The rich records stay in the tables, which is what makes the graph disposable: nothing is lost
    by throwing it away and rebuilding it from the release.
    """
    graph = sample()
    node_attributes = set(_nx.node_attributes(graph._graph, "a"))
    edge_attributes = set(_nx.edge_attributes(graph._graph, ("a", "b", "rel-1")))

    assert node_attributes | edge_attributes == TRAVERSAL_ATTRIBUTES
    assert set(NODE_COLUMNS) | set(EDGE_COLUMNS) == TRAVERSAL_ATTRIBUTES | {
        "element_id",
        "source_element_id",
        "target_element_id",
        "relationship_id",
    }


@pytest.mark.unit
@pytest.mark.requirement("CORE-23")
def test_parallel_relationships_keep_their_own_identities() -> None:
    """Two relationships between one pair are two edges, each keyed on its own canonical id."""
    graph = sample()

    assert graph.relationships_between("a", "b") == ("rel-1", "rel-2")
    assert graph.size == 2
    assert graph.order == 2
    assert graph.type_of(("a", "b", "rel-1")) == "contains"
    assert graph.type_of(("a", "b", "rel-2")) == "depends_on"
    assert graph.context_of(("a", "b", "rel-2")) == "ctx-1"
    assert graph.context_of(("a", "b", "rel-1")) is None


@pytest.mark.unit
@pytest.mark.requirement("CORE-25")
def test_the_graph_is_frozen_and_that_is_not_the_protection() -> None:
    """CORE-25 in one assertion pair: frozen against structure, open at the attribute dictionaries.

    `tests/qualification/test_networkx_stub.py` measures the second half against NetworkX itself.
    What this records is the consequence: the facade and the three-string attribute set are the
    real guard, and `freeze` is the cheap part.
    """
    graph = sample()

    assert graph.is_frozen()
    assert TRAVERSAL_ATTRIBUTES == {"kind_id", "relationship_type_id", "context_id"}


@pytest.mark.unit
@pytest.mark.requirement("CORE-24")
def test_asking_about_an_object_this_release_does_not_hold_names_the_release() -> None:
    graph = sample()

    with pytest.raises(GraphError, match="rel-0001"):
        graph.kind_of("not-here")
