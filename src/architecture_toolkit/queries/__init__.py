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
from architecture_toolkit.queries.execution import QueryResult, execute
from architecture_toolkit.queries.graph import ArchitectureGraph, build_graph, graph_from_rows
from architecture_toolkit.queries.plans import PlanEvidence, capture, write_evidence
from architecture_toolkit.queries.policy import (
    POLICIES,
    CycleHandling,
    Direction,
    GraphPolicy,
    policy_for,
)
from architecture_toolkit.queries.recipes import (
    RECIPES,
    ColumnSpec,
    ParameterSpec,
    QueryRecipe,
    TableInput,
    recipe_for,
)
from architecture_toolkit.queries.results import (
    GraphPathResult,
    PathClassification,
    TraversalResult,
)
from architecture_toolkit.queries.traversals import (
    find_interface_dependents,
    find_unverified_dependencies,
    trace_requirement_implementation,
)

__all__ = [
    "POLICIES",
    "RECIPES",
    "ArchitectureGraph",
    "ColumnSpec",
    "ComparisonContext",
    "CycleHandling",
    "Direction",
    "GraphError",
    "GraphPathResult",
    "GraphPolicy",
    "ParameterError",
    "ParameterSpec",
    "PathClassification",
    "PlanEvidence",
    "PolicyError",
    "QueryError",
    "QueryRecipe",
    "QueryResult",
    "RecipeError",
    "ReleaseContext",
    "ReleaseScope",
    "ResultContractError",
    "Side",
    "TableInput",
    "TraversalResult",
    "UnknownPolicyError",
    "UnknownRecipeError",
    "build_graph",
    "capture",
    "execute",
    "find_interface_dependents",
    "find_unverified_dependencies",
    "graph_from_rows",
    "policy_for",
    "recipe_for",
    "trace_requirement_implementation",
    "write_evidence",
]
