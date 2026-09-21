"""What every recipe must declare, checked as a class rather than one recipe at a time (DATA-48).

W4.1's lesson was that a test asserting one instance lets the next instance through. So the
assertions here are totality assertions: every declared field is either required of every recipe or
listed with the reason it is sometimes absent, and the two lists together must cover the model —
so a field added to `QueryRecipe` fails until somebody says which it is.

The same shape applies to parameters. A declaration that a recipe's SQL never uses and a
placeholder a recipe never declares are both silent failures: the first is a lie in the generated
schema contract, and the second reaches the engine as `No value found for placeholder`.
"""

import re

import pytest

from architecture_toolkit.domain.identifiers import IDENTIFIER_PATTERN
from architecture_toolkit.queries.errors import ParameterError, UnknownRecipeError
from architecture_toolkit.queries.recipes import (
    RECIPES,
    QueryRecipe,
    bind_parameters,
    declared_schema,
    recipe_for,
)
from architecture_toolkit.storage.schemas import BASELINE_TYPES, TABLE_IDS

PLACEHOLDER = re.compile(r"\$([a-z][a-z0-9_]*)")

REQUIRED_ON_EVERY_RECIPE = frozenset(
    {
        "query_recipe_id",
        "query_recipe_version",
        "purpose",
        "release_context",
        "inputs",
        "output_schema",
        "sql",
        "qualification_cases",
    }
)
"""The fields the `data.md § DataFusion` recipe fence names that no recipe may leave unset."""

POPULATED_WHERE_APPLICABLE = {
    "parameters": (
        "Three of the five recipes ask a fixed question and bind nothing. An invented parameter "
        "would be a worse contract than an honest empty one."
    ),
    "traversal_policy_id": (
        "Only a recipe whose answer corresponds to a graph traversal has traversal semantics; a "
        "relational recipe says so by leaving this unset rather than by omitting the field."
    ),
}
"""Fields a recipe may legitimately leave empty, each with the reason — the shape
`tests/strategies/__init__.py::DEFERRED_GROUPS` established, so a deferral stays distinguishable
from an oversight."""


@pytest.mark.unit
@pytest.mark.requirement("DATA-48")
def test_the_two_field_lists_cover_every_declared_field() -> None:
    """The guard on the guard: a new field on `QueryRecipe` fails until it is classified."""
    declared = set(QueryRecipe.model_fields)
    classified = REQUIRED_ON_EVERY_RECIPE | set(POPULATED_WHERE_APPLICABLE)

    assert classified == declared, (
        "add each new QueryRecipe field to REQUIRED_ON_EVERY_RECIPE, or to "
        "POPULATED_WHERE_APPLICABLE with the reason it can be absent"
    )


@pytest.mark.unit
@pytest.mark.requirement("DATA-48")
@pytest.mark.parametrize("recipe_id", sorted(RECIPES))
def test_every_required_field_is_populated(recipe_id: str) -> None:
    recipe = RECIPES[recipe_id]
    empty = sorted(
        name
        for name in REQUIRED_ON_EVERY_RECIPE
        if not getattr(recipe, name) and getattr(recipe, name) != 0
    )
    assert not empty, f"{recipe_id} leaves {empty} at their defaults"


@pytest.mark.unit
@pytest.mark.requirement("DATA-48", "DATA-18")
@pytest.mark.parametrize("recipe_id", sorted(RECIPES))
def test_declared_parameters_and_sql_placeholders_agree(recipe_id: str) -> None:
    """Both directions. One is a lie in the schema contract; the other fails at the engine."""
    recipe = RECIPES[recipe_id]
    declared = {spec.name for spec in recipe.parameters}
    referenced = set(PLACEHOLDER.findall(recipe.sql))

    assert declared == referenced, (
        f"{recipe_id} declares {sorted(declared - referenced)} it never uses and uses "
        f"{sorted(referenced - declared)} it never declares"
    )


@pytest.mark.unit
@pytest.mark.requirement("DATA-48", "DATA-15")
@pytest.mark.parametrize("recipe_id", sorted(RECIPES))
def test_a_recursive_recipe_declares_a_required_depth_bound(recipe_id: str) -> None:
    """Measured, not assumed: an unbounded recursion over a cyclic edge set does not terminate.

    `tests/qualification/test_datafusion_surface.py` pins that behaviour against DataFusion 54.
    This is the structural consequence — the bound is part of the recipe's contract, so a second
    recursive recipe cannot be added without one.
    """
    recipe = RECIPES[recipe_id]
    if not recipe.is_recursive:
        pytest.skip(f"{recipe_id} is not recursive")

    bounds = [
        spec
        for spec in recipe.parameters
        if spec.data_type == "integer" and spec.required and f"${spec.name}" in recipe.sql
    ]
    assert bounds, f"{recipe_id} recurses without a required integer bound"
    assert any("depth" in spec.name for spec in bounds)


@pytest.mark.unit
@pytest.mark.requirement("DATA-48")
@pytest.mark.parametrize("recipe_id", sorted(RECIPES))
def test_a_recipe_declares_the_sides_its_release_context_implies(recipe_id: str) -> None:
    """A comparison reads named sides; a single-release recipe reads none (DATA-47)."""
    recipe = RECIPES[recipe_id]
    sides = {item.side for item in recipe.inputs}

    if recipe.release_context == "comparison":
        assert sides == {"base", "candidate"}
    else:
        assert sides == {None}


@pytest.mark.unit
@pytest.mark.requirement("DATA-48")
@pytest.mark.parametrize("recipe_id", sorted(RECIPES))
def test_a_recipe_reads_only_real_tables_and_returns_only_persisted_types(recipe_id: str) -> None:
    recipe = RECIPES[recipe_id]

    assert {item.table_id for item in recipe.inputs} <= set(TABLE_IDS)
    assert all(field.type in BASELINE_TYPES for field in declared_schema(recipe))


@pytest.mark.unit
@pytest.mark.requirement("DATA-48")
def test_the_registry_is_keyed_on_the_recipe_id() -> None:
    assert all(key == recipe.query_recipe_id for key, recipe in RECIPES.items())
    assert all(re.fullmatch(IDENTIFIER_PATTERN, key) for key in RECIPES)


@pytest.mark.unit
@pytest.mark.requirement("DATA-48")
def test_an_unknown_recipe_is_refused_by_name() -> None:
    with pytest.raises(UnknownRecipeError, match="unknown query recipe"):
        recipe_for("no_such_recipe")


@pytest.mark.unit
@pytest.mark.requirement("DATA-18")
def test_an_undeclared_parameter_is_refused_before_the_engine() -> None:
    recipe = recipe_for("containment_hierarchy")

    with pytest.raises(ParameterError, match="does not declare"):
        bind_parameters(recipe, {"root_element_id": "a", "max_depth": 2, "sneaky": "x"})


@pytest.mark.unit
@pytest.mark.requirement("DATA-18")
def test_a_missing_required_parameter_names_the_recipe_and_the_purpose() -> None:
    recipe = recipe_for("containment_hierarchy")

    with pytest.raises(ParameterError, match="containment_hierarchy requires parameter"):
        bind_parameters(recipe, {"root_element_id": "a"})


@pytest.mark.unit
@pytest.mark.requirement("DATA-18")
def test_a_boolean_does_not_satisfy_an_integer_parameter() -> None:
    """`bool` is a subclass of `int`, so a naive check binds `True` as a depth of one."""
    recipe = recipe_for("containment_hierarchy")

    with pytest.raises(ParameterError, match="must be integer, got bool"):
        bind_parameters(recipe, {"root_element_id": "a", "max_depth": True})


@pytest.mark.unit
@pytest.mark.requirement("DATA-18")
def test_bound_parameters_are_returned_unchanged() -> None:
    recipe = recipe_for("containment_hierarchy")

    assert bind_parameters(recipe, {"root_element_id": "system-1", "max_depth": 3}) == {
        "root_element_id": "system-1",
        "max_depth": 3,
    }
