"""The named traversals, over a real published release (CORE-26..29, DATA-17).

Every assertion here is about a path rather than a set: CORE-28 says no impact result may discard
the justification, so a test that only checked *which* objects were reached would let a result type
that dropped the relationships pass.
"""

import pytest

from architecture_toolkit.domain.model import Model, Relationship
from architecture_toolkit.queries.context import ReleaseContext
from architecture_toolkit.queries.errors import GraphError
from architecture_toolkit.queries.graph import ArchitectureGraph, build_graph
from architecture_toolkit.queries.policy import policy_for
from architecture_toolkit.queries.results import PathClassification
from architecture_toolkit.queries.traversals import (
    find_interface_dependents,
    find_unverified_dependencies,
    trace_requirement_implementation,
)
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import Publisher


def graph_of(store: ReleaseStore, model: Model, publish_release: Publisher) -> ArchitectureGraph:
    manifest = publish_release("rel-0001", model, expected_parent=None)
    return build_graph(ReleaseContext.for_release(store, manifest))


def with_parallel_dependency(model: Model) -> Model:
    """A second relationship between the pair `rel-1` already joins (CORE-23).

    `system-1 depends_on component-1` alongside `system-1 contains component-1`: both endpoint
    kinds are permitted, so this publishes rather than being refused by the cross-record layer.
    """
    extra = Relationship(
        relationship_id="rel-10",
        model_id=model.model_id,
        relationship_type_id="depends_on",
        source_element_id="system-1",
        target_element_id="component-1",
    )
    return model.model_validate(dict(model) | {"relationships": (*model.relationships, extra)})


@pytest.mark.integration
@pytest.mark.requirement("CORE-28", "DATA-17")
def test_tracing_a_requirement_keeps_the_relationship_that_justifies_the_answer(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The example's only `realizes` edge runs `process-1` to `req-1`; the trace reverses it."""
    graph = graph_of(store, example_model, publish_release)

    result = trace_requirement_implementation(graph, "req-1")

    assert result.reached == ("process-1",)
    assert result.classification is PathClassification.TRACED
    path = result.paths[0]
    assert path.node_ids == ("req-1", "process-1")
    assert path.relationship_ids == ("rel-4",)
    assert path.relationship_types == ("realizes",)
    assert path.depth == 1
    assert path.policy_version == "1.0.0"
    assert path.release_id == "rel-0001"


@pytest.mark.integration
@pytest.mark.requirement("CORE-28", "DATA-17")
def test_finding_interface_dependents_reports_what_reaches_the_interface(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """`component-1 exposes interface-1`, so the reverse traversal finds the component."""
    graph = graph_of(store, example_model, publish_release)

    result = find_interface_dependents(graph, "interface-1")

    assert "component-1" in result.reached
    assert result.classification is PathClassification.POTENTIALLY_AFFECTED
    assert all(path.relationship_ids for path in result.paths)
    assert all(path.start == "interface-1" for path in result.paths)


@pytest.mark.integration
@pytest.mark.requirement("CORE-26", "DATA-17")
def test_the_impact_policy_does_not_follow_the_documentation_edge(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """`req-1 justifies system-1` exists in the example and must not appear in an impact answer.

    The negative control matters more than the positive one: a policy that followed everything
    would reach the same objects and nobody would notice until an impact report named a
    requirement author.
    """
    graph = graph_of(store, example_model, publish_release)

    result = graph.traverse(policy_for("impact.structural"), "req-1")

    assert "rel-7" not in {
        relationship for path in result.paths for relationship in path.relationship_ids
    }
    assert "system-1" not in result.reached


@pytest.mark.integration
@pytest.mark.requirement("CORE-23", "CORE-28")
def test_two_relationships_between_one_pair_produce_two_explainable_paths(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """CORE-29's edge-path requirement, end to end: the paths differ only in the relationship."""
    graph = graph_of(store, with_parallel_dependency(example_model), publish_release)

    result = graph.traverse(policy_for("impact.structural"), "system-1")
    direct = [path for path in result.paths if path.end == "component-1" and path.depth == 1]

    assert {path.relationship_ids for path in direct} == {("rel-1",), ("rel-10",)}
    assert {path.relationship_types for path in direct} == {("contains",), ("depends_on",)}


@pytest.mark.integration
@pytest.mark.requirement("CORE-29")
def test_a_capped_traversal_says_which_cap_stopped_it(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """A partial answer that looked complete would be worse than a slow query."""
    graph = graph_of(store, example_model, publish_release)
    impact = policy_for("impact.structural")

    generous = graph.traverse(impact, "system-1")
    assert not generous.truncated
    assert generous.limit_reached is None

    one_path = graph.traverse(impact.model_validate(dict(impact) | {"max_paths": 1}), "system-1")
    assert one_path.truncated
    assert one_path.limit_reached == "max_paths"
    assert len(one_path.paths) == 1

    one_result = graph.traverse(
        impact.model_validate(dict(impact) | {"max_results": 1}), "system-1"
    )
    assert one_result.truncated
    assert one_result.limit_reached == "max_results"
    assert len(set(one_result.reached)) == 1


@pytest.mark.integration
@pytest.mark.requirement("CORE-29")
def test_the_depth_cap_bounds_how_far_a_path_runs(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    graph = graph_of(store, example_model, publish_release)
    impact = policy_for("impact.structural")

    shallow = graph.traverse(impact.model_validate(dict(impact) | {"max_depth": 1}), "system-1")

    assert shallow.paths
    assert all(path.depth == 1 for path in shallow.paths)
    assert all(len(path.node_ids) == 2 for path in shallow.paths)


@pytest.mark.integration
@pytest.mark.requirement("CORE-27")
def test_a_policy_that_excludes_a_kind_stops_paths_passing_through_it(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The filtered view is where the exclusion happens, so the object is absent from every path."""
    graph = graph_of(store, example_model, publish_release)
    impact = policy_for("impact.structural")

    without_components = graph.traverse(
        impact.model_validate(dict(impact) | {"excluded_node_kinds": ("software.component",)}),
        "system-1",
    )

    assert "component-1" not in without_components.reached
    assert "component-1" not in {
        node for path in without_components.paths for node in path.node_ids
    }


@pytest.mark.integration
@pytest.mark.requirement("CORE-29")
def test_a_stop_kind_ends_a_path_without_removing_the_object(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The difference between a stop kind and an excluded kind, which is easy to conflate.

    An excluded kind is not in the view at all; a stop kind is reached and not passed through. A
    traversal that treated them the same would silently drop the boundary object from the answer.
    """
    graph = graph_of(store, example_model, publish_release)
    impact = policy_for("impact.structural")

    stopped = graph.traverse(
        impact.model_validate(dict(impact) | {"stop_kinds": ("software.component",)}),
        "system-1",
    )

    assert "component-1" in stopped.reached
    assert all(
        path.node_ids.index("component-1") == len(path.node_ids) - 1
        for path in stopped.paths
        if "component-1" in path.node_ids
    )


@pytest.mark.integration
@pytest.mark.requirement("DATA-17", "DATA-16")
def test_unverified_dependencies_join_the_traversal_to_the_release_it_came_from(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The traversal says what is reachable; the release's own table says what is known about it.

    Both come from one session, so the two halves cannot describe different releases. Every element
    in the example is `not_qualified`, so the filter keeps everything — and the assertion that
    carries weight is that the *paths* survive the filter, because an answer that named unverified
    dependencies without saying how they are reached would fail CORE-28.
    """
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    context = ReleaseContext.for_release(store, manifest)
    graph = build_graph(context)

    result = find_unverified_dependencies(graph, context, "interface-1")

    assert "schema-1" in result.reached
    assert all(path.relationship_ids for path in result.paths)
    assert result.policy_id == "dependencies.direct"


@pytest.mark.integration
@pytest.mark.requirement("CORE-24")
def test_traversing_from_an_object_the_release_does_not_hold_names_the_release(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    graph = graph_of(store, example_model, publish_release)

    with pytest.raises(GraphError, match="rel-0001"):
        graph.traverse(policy_for("impact.structural"), "not-here")
