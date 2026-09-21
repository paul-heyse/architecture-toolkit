"""The five shipped recipes, run against real published releases (DATA-48, DATA-15, DATA-47).

`execute` asserts the declared output schema on every call, so each of these cases is also a check
that the recipe's contract still describes what its SQL returns. The rows are what is asserted
here: a recipe that returned the right shape and the wrong answer would pass the contract check.
"""

import pytest

from architecture_toolkit.domain.details import VerificationMethod
from architecture_toolkit.domain.model import Element, Model
from architecture_toolkit.queries.context import ComparisonContext, ReleaseContext
from architecture_toolkit.queries.errors import ParameterError, ResultContractError
from architecture_toolkit.queries.execution import execute
from architecture_toolkit.queries.recipes import RECIPES, recipe_for
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import Publisher, rename_first_element


def replace_element(model: Model, element_id: str, changes: dict[str, object]) -> Model:
    return model.model_validate(
        dict(model)
        | {
            "elements": tuple(
                element.model_validate(dict(element) | changes)
                if element.element_id == element_id
                else element
                for element in model.elements
            )
        }
    )


def replace_detail(model: Model, element_id: str, changes: dict[str, object]) -> Model:
    owner = next(e for e in model.elements if e.element_id == element_id)
    assert owner.detail is not None
    detail = owner.detail.model_validate(dict(owner.detail) | changes)
    return replace_element(model, element_id, {"detail": detail})


def add_element(model: Model, element: Element) -> Model:
    return model.model_validate(dict(model) | {"elements": (*model.elements, element)})


SECOND_REVIEWER = "role-2"


def reassign_owner(model: Model) -> Model:
    """Move every `responsible_for` edge to a second role.

    A second *role*, not any element: publication runs the cross-record layer, and the baseline
    profile permits `responsible_for` only from `organization.role`. A comparison fixture that
    reassigned ownership to a component would be rejected before it was ever queried — which is
    the validation layer doing its job, and a reminder that a query fixture still has to be a
    model somebody could publish.
    """
    reviewer = Element(
        element_id=SECOND_REVIEWER,
        model_id=model.model_id,
        kind_id="organization.role",
        name="Second reviewer",
    )
    relocated = tuple(
        relationship.model_validate(dict(relationship) | {"source_element_id": SECOND_REVIEWER})
        if relationship.relationship_type_id == "responsible_for"
        else relationship
        for relationship in model.relationships
    )
    widened = add_element(model, reviewer)
    return widened.model_validate(dict(widened) | {"relationships": relocated})


@pytest.mark.integration
@pytest.mark.requirement("DATA-48")
@pytest.mark.parametrize("recipe_id", sorted(RECIPES))
def test_every_recipe_returns_the_schema_it_declared(
    recipe_id: str, store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """A recipe whose SQL drifts from its declaration fails the first time it runs."""
    base = publish_release("rel-0001", example_model, expected_parent=None)
    candidate = publish_release(
        "rel-0002", reassign_owner(example_model), expected_parent="rel-0001"
    )
    recipe = RECIPES[recipe_id]
    context: ReleaseContext | ComparisonContext = (
        ComparisonContext.of(store, base, candidate)
        if recipe.release_context == "comparison"
        else ReleaseContext.for_release(store, base)
    )
    parameters = {"root_element_id": "system-1", "max_depth": 5} if recipe.parameters else None

    result = execute(recipe, context, parameters)

    assert result.query_recipe_id == recipe_id
    assert result.table.schema.names == [column.name for column in recipe.output_schema]


@pytest.mark.integration
@pytest.mark.requirement("DATA-48", "DATA-15")
def test_an_unverified_requirement_is_reported_and_a_verified_one_is_not(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Both qualification cases the recipe declares, in one place so neither can be dropped."""
    verified = publish_release("rel-0001", example_model, expected_parent=None)
    unverified = publish_release(
        "rel-0002",
        replace_detail(
            example_model, "req-1", {"verification_method": VerificationMethod.NOT_ESTABLISHED}
        ),
        expected_parent="rel-0001",
    )
    recipe = recipe_for("requirements_without_verification")

    assert execute(recipe, ReleaseContext.for_release(store, verified)).table.num_rows == 0

    rows = execute(recipe, ReleaseContext.for_release(store, unverified)).table.to_pylist()
    assert [row["element_id"] for row in rows] == ["req-1"]
    assert rows[0]["applicability"] == "applicable"


@pytest.mark.integration
@pytest.mark.requirement("DATA-48")
def test_an_interface_without_a_request_schema_is_reported(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    declared = publish_release("rel-0001", example_model, expected_parent=None)
    missing = publish_release(
        "rel-0002",
        replace_detail(example_model, "interface-1", {"request_schema_id": None}),
        expected_parent="rel-0001",
    )
    recipe = recipe_for("interfaces_missing_request_schema")

    assert execute(recipe, ReleaseContext.for_release(store, declared)).table.num_rows == 0

    rows = execute(recipe, ReleaseContext.for_release(store, missing)).table.to_pylist()
    assert [row["element_id"] for row in rows] == ["interface-1"]


@pytest.mark.integration
@pytest.mark.requirement("DATA-48")
def test_an_uncovered_capability_is_reported_with_a_zero_rather_than_omitted(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """An absent row would make the uncovered capability invisible, which is the whole point."""
    orphan = Element(
        element_id="capability-2",
        model_id=example_model.model_id,
        kind_id="business.capability",
        name="Nobody supports this",
    )
    manifest = publish_release("rel-0001", add_element(example_model, orphan), expected_parent=None)

    rows = execute(
        recipe_for("capability_coverage_matrix"), ReleaseContext.for_release(store, manifest)
    ).table.to_pylist()
    by_id = {row["capability_id"]: row for row in rows}

    assert by_id["capability-1"] == {
        "capability_id": "capability-1",
        "capability_name": "Handle customer requests",
        "application_count": 1,
        "covered": True,
    }
    assert by_id["capability-2"]["application_count"] == 0
    assert by_id["capability-2"]["covered"] is False


@pytest.mark.integration
@pytest.mark.requirement("DATA-48", "DATA-47")
def test_ownership_is_compared_across_two_named_sides(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    base = publish_release("rel-0001", example_model, expected_parent=None)
    renamed = publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )
    reassigned = publish_release(
        "rel-0003", reassign_owner(example_model), expected_parent="rel-0002"
    )
    recipe = recipe_for("application_ownership_across_releases")

    # Two different releases whose ownership is the same: the recipe must not invent a change.
    unchanged = execute(recipe, ComparisonContext.of(store, base, renamed))
    assert unchanged.table.to_pylist() == [
        {"element_id": "process-1", "base_owner": "role-1", "candidate_owner": "role-1"}
    ]

    changed = execute(recipe, ComparisonContext.of(store, base, reassigned))
    assert changed.table.to_pylist() == [
        {"element_id": "process-1", "base_owner": "role-1", "candidate_owner": SECOND_REVIEWER}
    ]
    assert changed.release_ids == ("rel-0001", "rel-0003")


@pytest.mark.integration
@pytest.mark.requirement("DATA-48", "DATA-15")
def test_the_recursive_recipe_descends_and_stops_where_it_is_told(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    context = ReleaseContext.for_release(store, manifest)
    recipe = recipe_for("containment_hierarchy")

    rows = execute(
        recipe, context, {"root_element_id": "system-1", "max_depth": 5}
    ).table.to_pylist()
    assert rows == [
        {
            "element_id": "component-1",
            "name": "Request handler",
            "relationship_id": "rel-1",
            "depth": 1,
        }
    ]

    assert (
        execute(recipe, context, {"root_element_id": "component-1", "max_depth": 5}).table.num_rows
        == 0
    )


@pytest.mark.integration
@pytest.mark.requirement("DATA-48")
def test_a_recipe_run_against_the_wrong_kind_of_context_is_refused_by_name(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Otherwise the failure is `failed to resolve schema: base`, which names no recipe."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    recipe = recipe_for("application_ownership_across_releases")

    with pytest.raises(ParameterError, match="needs a comparison release context"):
        execute(recipe, ReleaseContext.for_release(store, manifest))


@pytest.mark.integration
@pytest.mark.requirement("DATA-48")
def test_sql_that_drifts_from_the_declaration_fails_the_contract(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The negative control: without it, the schema check could be vacuous and nobody would know."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    recipe = recipe_for("requirements_without_verification")
    drifted = recipe.model_validate(
        dict(recipe) | {"sql": "SELECT element_id FROM elements ORDER BY element_id"}
    )

    with pytest.raises(ResultContractError, match="declared"):
        execute(drifted, ReleaseContext.for_release(store, manifest))
