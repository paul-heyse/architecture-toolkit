"""A recipe that claims traversal semantics is held to them (DATA-48, DATA-16, CORE-30).

`QueryRecipe.traversal_policy_id` is `data.md`'s "applicable traversal semantics". A recipe that
names a policy is making a claim: that the relational answer and the graph answer are answers to
the same question. This is where that claim is checked, on a real release, through both engines
built from one session.

It is the hard gate turned around. The gate asserts the two surfaces read the same release; this
asserts that where they are asked the same question, they give the same answer — which is the part
that would actually go wrong first, because SQL and a traversal are easy to drift apart while both
still reading the right versions.
"""

import pytest

from architecture_toolkit.domain.model import Model, Relationship
from architecture_toolkit.queries.algorithms import cycles
from architecture_toolkit.queries.context import ReleaseContext
from architecture_toolkit.queries.errors import PolicyError
from architecture_toolkit.queries.execution import execute
from architecture_toolkit.queries.graph import build_graph
from architecture_toolkit.queries.policy import policy_for
from architecture_toolkit.queries.recipes import RECIPES
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import Publisher

CLAIMED = sorted(
    recipe.query_recipe_id for recipe in RECIPES.values() if recipe.traversal_policy_id is not None
)


def deeper(model: Model) -> Model:
    """Two levels of containment, so the comparison is not trivially one edge.

    `component-1 contains interface-1` is permitted by the baseline profile, and `interface-1` has
    no containment parent yet, so the single-parent rule is satisfied and this publishes.
    """
    extra = Relationship(
        relationship_id="rel-11",
        model_id=model.model_id,
        relationship_type_id="contains",
        source_element_id="component-1",
        target_element_id="interface-1",
    )
    return model.model_validate(dict(model) | {"relationships": (*model.relationships, extra)})


@pytest.mark.integration
@pytest.mark.requirement("DATA-48")
def test_at_least_one_recipe_claims_traversal_semantics() -> None:
    """Otherwise the comparison below has nothing to compare and would pass forever."""
    assert CLAIMED == ["containment_hierarchy"]


@pytest.mark.integration
@pytest.mark.requirement("DATA-48", "DATA-16", "CORE-30")
@pytest.mark.parametrize("recipe_id", CLAIMED)
def test_the_recipe_and_the_policy_it_names_answer_the_same_question(
    recipe_id: str, store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    manifest = publish_release("rel-0001", deeper(example_model), expected_parent=None)
    context = ReleaseContext.for_release(store, manifest)
    recipe = RECIPES[recipe_id]
    assert recipe.traversal_policy_id is not None
    policy = policy_for(recipe.traversal_policy_id)

    relational = execute(
        recipe, context, {"root_element_id": "system-1", "max_depth": policy.max_depth}
    ).table.to_pylist()
    traversed = build_graph(context).traverse(policy, "system-1")

    assert {row["element_id"] for row in relational} == set(traversed.reached)
    assert {row["relationship_id"] for row in relational} == {
        relationship for path in traversed.paths for relationship in path.relationship_ids
    }
    assert {row["element_id"] for row in relational} == {"component-1", "interface-1"}
    assert {row["depth"] for row in relational} == {1, 2}


@pytest.mark.integration
@pytest.mark.requirement("CORE-30")
def test_a_policy_that_does_not_declare_cycle_reporting_is_refused_the_analysis(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """CORE-30's "only under explicit graph semantics", as a refusal rather than a convention.

    `impact.structural` is the policy somebody would reach for first, and it has not said what a
    cycle in its view would mean. `containment.descendants` has.
    """
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    graph = build_graph(ReleaseContext.for_release(store, manifest))

    with pytest.raises(PolicyError, match="cycle_handling=skip"):
        cycles(graph, policy_for("impact.structural"))

    assert cycles(graph, policy_for("containment.descendants")) == ()
