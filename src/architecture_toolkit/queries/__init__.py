"""Release-bound DataFusion catalogs and typed, policy-driven NetworkX traversals.

Both read surfaces are reconstructed from one selected `ArchitectureRelease`, so they cannot
disagree about what the model is. The graph is built *from* the query session rather than beside
it, which is what makes the M3 hard gate — "DataFusion and NetworkX read the same release" — a
property of there being one session rather than an assertion about two code paths.

Delta is reached only through a storage `SnapshotProvider` (`rules/queries-no-direct-delta.yml`)
and NetworkX only through `queries/_nx.py` (`rules/graph-networkx-only-in-adapter.yml`).
"""

from architecture_toolkit.queries.context import (
    ComparisonContext,
    ReleaseContext,
    ReleaseScope,
    Side,
)
from architecture_toolkit.queries.errors import (
    GraphError,
    ParameterError,
    PolicyError,
    QueryError,
    RecipeError,
    ResultContractError,
    UnknownPolicyError,
    UnknownRecipeError,
)

__all__ = [
    "ComparisonContext",
    "GraphError",
    "ParameterError",
    "PolicyError",
    "QueryError",
    "RecipeError",
    "ReleaseContext",
    "ReleaseScope",
    "ResultContractError",
    "Side",
    "UnknownPolicyError",
    "UnknownRecipeError",
]
