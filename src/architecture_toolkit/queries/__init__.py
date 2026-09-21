"""Release-bound DataFusion catalogs and typed, policy-driven NetworkX traversals.

Both read surfaces are reconstructed from one selected `ArchitectureRelease`, so they cannot
disagree about what the model is. The graph is built *from* the query session rather than beside
it, which is what makes the M3 hard gate — "DataFusion and NetworkX read the same release" — a
property of there being one session rather than an assertion about two code paths.

Delta is reached only through a storage `SnapshotProvider` (`rules/queries-no-direct-delta.yml`)
and NetworkX only through `queries/_nx.py` (`rules/graph-networkx-only-in-adapter.yml`).
"""

from architecture_toolkit.queries.algorithms import (
    ancestors,
    compare_architecture_releases,
    components,
    condensation,
    cycles,
    descendants,
    find_containment_cycles,
    generations,
    is_acyclic,
    minimum_equivalent,
    reachability_closure,
)
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
from architecture_toolkit.queries.execution import (
    QueryResult,
    ReleaseQueryExecutor,
    execute,
)
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
    ComponentResult,
    CondensationResult,
    CycleResult,
    GraphPathResult,
    PathClassification,
    ReachabilityEdge,
    ReductionEdge,
    ReleaseComparison,
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
    "ComponentResult",
    "CondensationResult",
    "CycleHandling",
    "CycleResult",
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
    "ReachabilityEdge",
    "RecipeError",
    "ReductionEdge",
    "ReleaseComparison",
    "ReleaseContext",
    "ReleaseQueryExecutor",
    "ReleaseScope",
    "ResultContractError",
    "Side",
    "TableInput",
    "TraversalResult",
    "UnknownPolicyError",
    "UnknownRecipeError",
    "ancestors",
    "build_graph",
    "capture",
    "compare_architecture_releases",
    "components",
    "condensation",
    "cycles",
    "descendants",
    "execute",
    "find_containment_cycles",
    "find_interface_dependents",
    "find_unverified_dependencies",
    "generations",
    "graph_from_rows",
    "is_acyclic",
    "minimum_equivalent",
    "policy_for",
    "reachability_closure",
    "recipe_for",
    "trace_requirement_implementation",
    "write_evidence",
]
