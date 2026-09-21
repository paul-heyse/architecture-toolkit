"""Structural analyses over a real release, and what each result keeps (CORE-30, CORE-31)."""

import pytest

from architecture_toolkit.domain.model import Model, Relationship
from architecture_toolkit.queries.algorithms import (
    ancestors,
    compare_architecture_releases,
    components,
    condensation,
    descendants,
    find_containment_cycles,
    generations,
    is_acyclic,
    minimum_equivalent,
    reachability_closure,
)
from architecture_toolkit.queries.context import ReleaseContext
from architecture_toolkit.queries.errors import GraphError
from architecture_toolkit.queries.graph import ArchitectureGraph, build_graph, graph_from_rows
from architecture_toolkit.queries.policy import policy_for
from architecture_toolkit.queries.results import ReachabilityEdge
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import Publisher

DIGEST = "sha256:" + "0" * 64
CONTAINMENT = policy_for("containment.descendants")
IMPACT = policy_for("impact.structural")


def published_graph(
    store: ReleaseStore, model: Model, publish_release: Publisher
) -> ArchitectureGraph:
    manifest = publish_release("rel-0001", model, expected_parent=None)
    return build_graph(ReleaseContext.for_release(store, manifest))


def cyclic_containment() -> ArchitectureGraph:
    """A containment cycle with one step realized twice.

    `contains` declares the `acyclic` rule, so publication refuses this; the graph is assembled
    directly, which is the case `find_containment_cycles` exists for — a store written by
    something that did not validate.
    """
    return graph_from_rows(
        release_id="rel-0001",
        model_id="sample-service",
        model_digest=DIGEST,
        nodes=[("sys-a", "software.system"), ("cmp-b", "software.component")],
        edges=[
            ("sys-a", "cmp-b", "rel-1", "contains", None),
            ("sys-a", "cmp-b", "rel-2", "contains", None),
            ("cmp-b", "sys-a", "rel-3", "contains", None),
        ],
    )


@pytest.mark.integration
@pytest.mark.requirement("CORE-30")
def test_ancestors_and_descendants_answer_under_one_policy(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """ "Is this reachable" has no answer until somebody says which relationships count."""
    graph = published_graph(store, example_model, publish_release)

    assert descendants(graph, CONTAINMENT, "system-1") == frozenset({"component-1"})
    assert ancestors(graph, CONTAINMENT, "component-1") == frozenset({"system-1"})
    assert "interface-1" in descendants(graph, IMPACT, "system-1")
    assert "interface-1" not in descendants(graph, CONTAINMENT, "system-1")


@pytest.mark.integration
@pytest.mark.requirement("CORE-30")
def test_topological_generations_are_refused_where_the_view_is_cyclic(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """A partial ordering nobody could tell from a complete one is worse than a refusal."""
    acyclic = published_graph(store, example_model, publish_release)

    assert is_acyclic(acyclic, CONTAINMENT)
    assert generations(acyclic, CONTAINMENT)[0] != ()

    cyclic = cyclic_containment()
    assert not is_acyclic(cyclic, CONTAINMENT)
    with pytest.raises(GraphError, match="topological ordering"):
        generations(cyclic, CONTAINMENT)


@pytest.mark.integration
@pytest.mark.requirement("CORE-30", "CORE-23")
def test_a_cycle_reports_every_relationship_that_realizes_it() -> None:
    """`simple_cycles` keeps no keys; two parallel relationships closing a cycle are two facts."""
    found = find_containment_cycles(cyclic_containment())

    # Sorted, because `simple_cycles` is free to start the rotation anywhere; what must hold is
    # that both realizations are reported and neither invents a relationship.
    assert {tuple(sorted(result.relationship_ids)) for result in found} == {
        ("rel-1", "rel-3"),
        ("rel-2", "rel-3"),
    }
    assert all(set(result.node_ids) == {"sys-a", "cmp-b"} for result in found)
    assert all(result.length == 2 for result in found)
    assert all(result.policy_id == "containment.descendants" for result in found)


@pytest.mark.integration
@pytest.mark.requirement("CORE-30")
def test_a_published_model_has_no_containment_cycle(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The negative control: the validator refuses one, so the analysis must agree."""
    graph = published_graph(store, example_model, publish_release)

    assert find_containment_cycles(graph) == ()


@pytest.mark.integration
@pytest.mark.requirement("CORE-30")
def test_components_and_their_condensation_map_back_to_canonical_ids() -> None:
    cyclic = cyclic_containment()

    found = components(cyclic, CONTAINMENT)
    assert found[0].element_ids == ("cmp-b", "sys-a")
    assert found[0].is_cyclic

    collapsed = condensation(cyclic, CONTAINMENT)
    assert [component.element_ids for component in collapsed.components] == [("cmp-b", "sys-a")]
    assert collapsed.edges == ()


@pytest.mark.integration
@pytest.mark.requirement("CORE-30")
def test_a_single_element_is_a_component_and_is_not_cyclic(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Otherwise every object in an acyclic model would be reported as a dependency cycle."""
    graph = published_graph(store, example_model, publish_release)

    found = components(graph, CONTAINMENT)

    # `all` over an empty sequence is true, so the count comes first: without it this test would
    # pass just as happily if `components` returned nothing at all.
    assert len(found) == len(example_model.elements)
    assert all(not component.is_cyclic for component in found)
    assert all(len(component.element_ids) == 1 for component in found)


@pytest.mark.integration
@pytest.mark.requirement("CORE-31")
def test_a_closure_edge_carries_no_relationship_identity(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Derived analysis never replaces canonical relationships, enforced by the missing field."""
    graph = published_graph(store, example_model, publish_release)

    closure = reachability_closure(graph, IMPACT)

    assert ReachabilityEdge(source="system-1", target="schema-1") in closure
    assert "relationship_ids" not in ReachabilityEdge.model_fields
    assert ("system-1", "schema-1") not in {(edge[0], edge[1]) for edge in graph.edges()}, (
        "the closure edge is derived; no relationship joins that pair"
    )


@pytest.mark.integration
@pytest.mark.requirement("CORE-31")
def test_a_reduction_edge_names_every_relationship_that_backs_it(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """`transitive_reduction` returns a DiGraph and drops the keys, so they are recovered."""
    graph = published_graph(store, example_model, publish_release)

    reduced = minimum_equivalent(graph, CONTAINMENT)

    by_pair = {(edge.source, edge.target): edge.relationship_ids for edge in reduced}
    assert by_pair[("system-1", "component-1")] == ("rel-1",)
    assert all(edge.relationship_ids for edge in reduced)


@pytest.mark.integration
@pytest.mark.requirement("CORE-31")
def test_a_reduction_is_refused_where_the_view_is_cyclic() -> None:
    with pytest.raises(GraphError, match="defined only for a DAG"):
        minimum_equivalent(cyclic_containment(), CONTAINMENT)


@pytest.mark.integration
@pytest.mark.requirement("DATA-17")
def test_comparing_two_releases_reports_a_retyped_relationship(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The case a set difference reports as no change: same identity, different meaning."""
    base = published_graph(store, example_model, publish_release)
    retyped = graph_from_rows(
        release_id="rel-0002",
        model_id=example_model.model_id,
        model_digest=DIGEST,
        nodes=((element.element_id, element.kind_id) for element in example_model.elements),
        edges=(
            (
                relationship.source_element_id,
                relationship.target_element_id,
                relationship.relationship_id,
                "depends_on"
                if relationship.relationship_id == "rel-1"
                else relationship.relationship_type_id,
                relationship.context_id,
            )
            for relationship in example_model.relationships
        ),
    )

    comparison = compare_architecture_releases(base, retyped)

    assert comparison.retyped_relationships == (("rel-1", "contains", "depends_on"),)
    assert comparison.added_relationships == ()
    assert comparison.removed_relationships == ()
    assert not comparison.is_empty


@pytest.mark.integration
@pytest.mark.requirement("DATA-17")
def test_comparing_a_release_with_itself_reports_nothing(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    graph = published_graph(store, example_model, publish_release)

    assert compare_architecture_releases(graph, graph).is_empty


@pytest.mark.integration
@pytest.mark.requirement("DATA-17")
def test_comparing_releases_reports_an_added_object_and_its_relationship(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    base = published_graph(store, example_model, publish_release)
    extra = Relationship(
        relationship_id="rel-10",
        model_id=example_model.model_id,
        relationship_type_id="depends_on",
        source_element_id="system-1",
        target_element_id="component-1",
    )
    widened = example_model.model_validate(
        dict(example_model) | {"relationships": (*example_model.relationships, extra)}
    )
    candidate = graph_from_rows(
        release_id="rel-0002",
        model_id=widened.model_id,
        model_digest=DIGEST,
        nodes=((element.element_id, element.kind_id) for element in widened.elements),
        edges=(
            (
                relationship.source_element_id,
                relationship.target_element_id,
                relationship.relationship_id,
                relationship.relationship_type_id,
                relationship.context_id,
            )
            for relationship in widened.relationships
        ),
    )

    comparison = compare_architecture_releases(base, candidate)

    assert comparison.added_relationships == ("rel-10",)
    assert comparison.added_elements == ()
    assert comparison.base_release_id == "rel-0001"
    assert comparison.candidate_release_id == "rel-0002"
