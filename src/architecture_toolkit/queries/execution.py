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
from dataclasses import dataclass, field

import pyarrow as pa

from architecture_toolkit.domain.identifiers import QueryRecipeId, ReleaseId, SchemaVersion
from architecture_toolkit.queries.context import ComparisonContext, ReleaseContext
from architecture_toolkit.queries.errors import ParameterError, QueryError, ResultContractError
from architecture_toolkit.queries.graph import ArchitectureGraph, build_graph
from architecture_toolkit.queries.recipes import (
    QueryRecipe,
    bind_parameters,
    declared_schema,
    recipe_for,
)
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.snapshot import DEFAULT_PROVIDER

__all__ = ["QueryResult", "ReleaseQueryExecutor", "execute"]

# `execute` is the free function a caller with a context already in hand uses;
# `ReleaseQueryExecutor` is for a caller holding release *ids*, and it is what satisfies
# `domain.protocols.QueryExecutor`.


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


@dataclass(eq=False, slots=True)
class ReleaseQueryExecutor:
    """Runs recipes by id against releases by id, satisfying `domain.protocols.QueryExecutor`.

    Everything below this exists because the caller that has a release *id* — the CLI, a future
    portal, an agent — has to resolve it to a context, find the recipe, and run it, and doing that
    inline is how three commands ended up with the same eight lines. Building the context is the
    expensive part, so it is memoised per release: a session registers eleven Delta versions, and
    a command that queries and then traverses should not do it twice.

    Not frozen and not hashable (`eq=False`), because the cache is state. That is the one mutable
    object in the query layer and it holds no architecture facts — only sessions, which are
    rebuilt from the manifest every time this object is.
    """

    store: ReleaseStore
    provider: str = DEFAULT_PROVIDER
    _contexts: dict[ReleaseId, ReleaseContext] = field(default_factory=dict, repr=False)

    def context_for(self, release_id: ReleaseId) -> ReleaseContext:
        """The session for one release, built once."""
        cached = self._contexts.get(release_id)
        if cached is None:
            manifest = self.store.read_manifest(release_id)
            cached = ReleaseContext.for_release(self.store, manifest, provider=self.provider)
            self._contexts[release_id] = cached
        return cached

    def current(self) -> ReleaseId:
        """The release a command means when it names none."""
        release_id = self.store.current_id()
        if release_id is None:
            message = f"no current release in {self.store.root}; publish one first"
            raise QueryError(message)
        return release_id

    def answer(
        self,
        recipe_id: str,
        *,
        release_id: ReleaseId,
        parameters: Mapping[str, object] | None = None,
    ) -> QueryResult:
        """Run one single-release recipe, with the provenance a caller needs to report it."""
        recipe = recipe_for(recipe_id)
        if recipe.release_context != "single":
            message = f"{recipe_id} compares two releases; name them with --base and --candidate"
            raise ParameterError(message)
        return execute(recipe, self.context_for(release_id), parameters)

    def compare(
        self,
        recipe_id: str,
        *,
        base_release_id: ReleaseId,
        candidate_release_id: ReleaseId,
        parameters: Mapping[str, object] | None = None,
    ) -> QueryResult:
        """Run one comparison recipe across two named sides (DATA-47)."""
        recipe = recipe_for(recipe_id)
        if recipe.release_context != "comparison":
            message = f"{recipe_id} reads one release; name it with --release, not two sides"
            raise ParameterError(message)
        comparison = ComparisonContext.of(
            self.store,
            self.store.read_manifest(base_release_id),
            self.store.read_manifest(candidate_release_id),
            provider=self.provider,
        )
        return execute(recipe, comparison, parameters)

    def graph_for(self, release_id: ReleaseId) -> ArchitectureGraph:
        """The same release as a graph, projected from the session the recipes use.

        Here rather than at the call site so the hard gate cannot be lost by accident: a caller
        that builds a graph from one context and runs a recipe against another has two releases,
        and nothing in its code would say so.
        """
        return build_graph(self.context_for(release_id))

    def execute(self, recipe_id: str, *, release_id: str) -> pa.Table:
        """`domain.protocols.QueryExecutor`. The rows alone; `answer` carries the provenance."""
        return self.answer(recipe_id, release_id=release_id).table
