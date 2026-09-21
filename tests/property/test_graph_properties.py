"""Invariants a bounded traversal must hold for any model, not only the example (CORE-28, CORE-29).

The integration tests assert what the traversals answer for one carefully-built release. These
assert the properties that must hold whatever the model is — that a cap is a cap, that every id in
a result is an id the model declares, and that a reported path is a walk somebody could follow.

`tests/strategies.coherent_models` deliberately generates models with cycles, self-loops, parallel
edges and impermissible endpoint kinds. That is the point: a traversal has to be bounded on a graph
nobody curated, and the awkward shapes are exactly where an off-by-one in a cap lives.
"""

import pytest
from hypothesis import given

from architecture_toolkit.domain.model import Model
from architecture_toolkit.queries.graph import ArchitectureGraph, graph_from_rows
from architecture_toolkit.queries.policy import POLICIES, GraphPolicy
from tests.strategies import coherent_models

DIGEST = "sha256:" + "0" * 64


def graph_of(model: Model) -> ArchitectureGraph:
    return graph_from_rows(
        release_id="rel-0001",
        model_id=model.model_id,
        model_digest=DIGEST,
        nodes=((element.element_id, element.kind_id) for element in model.elements),
        edges=(
            (
                relationship.source_element_id,
                relationship.target_element_id,
                relationship.relationship_id,
                relationship.relationship_type_id,
                relationship.context_id,
            )
            for relationship in model.relationships
        ),
    )


@pytest.mark.property
@pytest.mark.requirement("CORE-29")
@given(model=coherent_models())
def test_no_traversal_ever_exceeds_the_caps_its_policy_declares(model: Model) -> None:
    graph = graph_of(model)
    tight = {
        policy_id: policy.model_validate(
            dict(policy) | {"max_depth": 2, "max_paths": 3, "max_results": 2}
        )
        for policy_id, policy in POLICIES.items()
    }

    for policy in tight.values():
        for element in model.elements:
            result = graph.traverse(policy, element.element_id)
            assert len(result.paths) <= policy.max_paths
            assert len(set(result.reached)) <= policy.max_results
            assert all(path.depth <= policy.max_depth for path in result.paths)


@pytest.mark.property
@pytest.mark.requirement("CORE-28", "CORE-30")
@given(model=coherent_models())
def test_every_id_in_a_result_is_one_the_model_declares(model: Model) -> None:
    """CORE-30's "retain mappings to canonical IDs", as a property rather than an example."""
    graph = graph_of(model)
    element_ids = {element.element_id for element in model.elements}
    relationship_ids = {relationship.relationship_id for relationship in model.relationships}

    for policy in POLICIES.values():
        for element in model.elements:
            result = graph.traverse(policy, element.element_id)
            for path in result.paths:
                assert set(path.node_ids) <= element_ids
                assert set(path.relationship_ids) <= relationship_ids
                assert path.start == element.element_id
                assert path.end == path.node_ids[-1]


@pytest.mark.property
@pytest.mark.requirement("CORE-28")
@given(model=coherent_models())
def test_a_reported_path_is_a_walk_somebody_could_follow(model: Model) -> None:
    """The justification has to justify: each step's relationship must join consecutive nodes.

    Direction is the policy's, so the check is orientation-agnostic — a reverse traversal reports
    the same relationship, walked the other way.
    """
    graph = graph_of(model)
    by_id = {
        relationship.relationship_id: (
            relationship.source_element_id,
            relationship.target_element_id,
        )
        for relationship in model.relationships
    }

    for policy in POLICIES.values():
        for element in model.elements:
            for path in graph.traverse(policy, element.element_id).paths:
                assert len(path.node_ids) == len(path.relationship_ids) + 1
                assert len(path.relationship_types) == len(path.relationship_ids)
                for index, relationship_id in enumerate(path.relationship_ids):
                    step = {path.node_ids[index], path.node_ids[index + 1]}
                    assert set(by_id[relationship_id]) == step or step <= set(
                        by_id[relationship_id]
                    )


@pytest.mark.property
@pytest.mark.requirement("CORE-27")
@given(model=coherent_models())
def test_a_traversal_only_ever_follows_the_types_its_policy_allows(model: Model) -> None:
    graph = graph_of(model)
    allowed: dict[str, GraphPolicy] = dict(POLICIES)

    for policy in allowed.values():
        for element in model.elements:
            for path in graph.traverse(policy, element.element_id).paths:
                assert set(path.relationship_types) <= set(policy.allowed_relationship_types)
