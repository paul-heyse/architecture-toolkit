"""Running a declared recipe against the release context it says it needs (DATA-48, DATA-18).

Separate from `queries/recipes.py` because the declarations are a generated JSON Schema contract —
`contracts.py` emits the `query-contract` family from them — and a schema contract is a different
kind of thing from the code that runs a query. Editing what a recipe promises and editing how a
recipe is executed are different reviews.

Two refusals happen here that would otherwise reach the caller as engine noise. A recipe run
against the wrong kind of context fails with the recipe's name rather than
`failed to resolve schema: base`. And a result whose schema disagrees with the declaration fails
here, which is what makes `expected output schema` a contract instead of a comment: a recipe whose
SQL is edited without its declaration being edited fails the first time it runs.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import pyarrow as pa

from architecture_toolkit.domain.identifiers import QueryRecipeId, ReleaseId, SchemaVersion
from architecture_toolkit.queries.context import ComparisonContext, ReleaseContext
from architecture_toolkit.queries.errors import ParameterError, ResultContractError
from architecture_toolkit.queries.recipes import QueryRecipe, bind_parameters, declared_schema

__all__ = ["QueryResult", "execute"]


@dataclass(frozen=True, slots=True)
class QueryResult:
    """An answer, with the provenance needed to say which releases produced it."""

    query_recipe_id: QueryRecipeId
    query_recipe_version: SchemaVersion
    release_ids: tuple[ReleaseId, ...]
    table: pa.Table


def execute(
    recipe: QueryRecipe,
    context: ReleaseContext | ComparisonContext,
    parameters: Mapping[str, object] | None = None,
) -> QueryResult:
    """Run one recipe against the release context it declares it needs."""
    bound = bind_parameters(recipe, parameters)
    releases = _releases(recipe, context)
    frame = context.sql(recipe.sql, bound or None)
    observed = frame.schema()
    expected = declared_schema(recipe)
    if not observed.equals(expected):
        message = (
            f"{recipe.query_recipe_id} v{recipe.query_recipe_version} declared\n{expected}\n"
            f"and returned\n{observed}"
        )
        raise ResultContractError(message)
    return QueryResult(
        query_recipe_id=recipe.query_recipe_id,
        query_recipe_version=recipe.query_recipe_version,
        release_ids=releases,
        table=frame.to_arrow_table(),
    )


def _releases(
    recipe: QueryRecipe, context: ReleaseContext | ComparisonContext
) -> tuple[ReleaseId, ...]:
    """Refuse a recipe run against the wrong kind of context, and report which releases it read.

    A comparison recipe run against a single-release context fails in the planner with "failed to
    resolve schema: base", which says nothing about the recipe. The other direction is worse: a
    single-release recipe's unqualified names would resolve against `public`, which a comparison
    never populates, so the failure would be equally opaque.
    """
    match (recipe.release_context, context):
        case ("single", ReleaseContext()):
            return (context.scope.release_id,)
        case ("comparison", ComparisonContext()):
            return (context.base.release_id, context.candidate.release_id)
        case _:
            message = (
                f"{recipe.query_recipe_id} needs a {recipe.release_context} release context, "
                f"got {type(context).__name__}"
            )
            raise ParameterError(message)
