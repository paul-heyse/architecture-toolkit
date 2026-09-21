"""What the query layer refuses, and why each refusal is its own type.

The split mirrors `storage/errors.py`: a caller that catches one of these has to decide something
different in each case. A recipe that does not exist is a typo; a parameter that does not match a
recipe's declared schema is a caller mistake; a result whose schema disagrees with what the recipe
promised is a *contract* failure and means the recipe changed without its declaration changing; a
policy that names a relationship type the profile forbids traversing is a policy bug; and a DAG
algorithm asked of a cyclic view is a question that has no answer rather than a failure to compute
one.

None of these is a `Diagnostic`. Diagnostics say something about the model; these say something
about the query. `validation/codes.py` stays about the model.
"""

__all__ = [
    "GraphError",
    "ParameterError",
    "PolicyError",
    "QueryError",
    "RecipeError",
    "ResultContractError",
    "UnknownPolicyError",
    "UnknownRecipeError",
]


class QueryError(Exception):
    """Base for every failure the query layer raises on its own account."""


class RecipeError(QueryError):
    """A versioned query recipe is not usable as declared."""


class UnknownRecipeError(RecipeError, KeyError):
    """A recipe id that is not in the registry.

    `KeyError` as well, for the same reason `UnknownTableError` is: the registry is a mapping and
    a caller indexing it should be able to catch what indexing a mapping normally raises.
    """


class ParameterError(RecipeError):
    """Bound parameters do not satisfy the recipe's declared parameter schema.

    Raised before the query reaches the engine. A missing required parameter would otherwise
    surface as a DataFusion planning error naming a placeholder, which tells the caller nothing
    about which recipe promised what.
    """


class ResultContractError(RecipeError):
    """The engine returned a schema the recipe did not declare (DATA-48).

    This is the check that makes `expected output schema` more than documentation: a recipe whose
    SQL is edited without its declaration being edited fails the first time it runs.
    """


class PolicyError(QueryError):
    """A graph policy is not coherent with the profile it would traverse."""


class UnknownPolicyError(PolicyError, KeyError):
    """A policy id that is not in the registry."""


class GraphError(QueryError):
    """A graph question that cannot be answered as asked.

    A DAG algorithm over a view that contains a cycle is the common case. Returning a partial
    answer would be worse than refusing, because the caller cannot tell the difference.
    """
