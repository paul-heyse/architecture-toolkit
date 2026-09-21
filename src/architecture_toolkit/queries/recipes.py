"""Versioned, parameterized query recipes and the contract each one keeps (DATA-48, DATA-15).

`data.md § DataFusion` fixes the fields a recipe carries, and this module is that fence as a type:
id and version, purpose, input table roles, parameter schema, expected output schema, required
release context, the SQL, applicable traversal semantics and qualification cases. Declaring them
is only half the value; the other half is that both halves are *checked*.

**Parameters are bound, never interpolated.** `tests/qualification/test_data_stack.py` already
qualified DataFusion for that — the injection case returns zero rows rather than every row — so
this module does not re-prove it. What it adds is the refusal that happens before the engine is
reached: an undeclared parameter, a missing required one or one of the wrong type is a
`ParameterError` naming the recipe, not a DataFusion planning error naming a placeholder.

**The declared output schema is enforced.** After a recipe runs, its result schema must equal what
it declared. That is what stops `expected output schema` from being documentation: a recipe whose
SQL is edited without its declaration being edited fails the first time it runs, rather than
returning a differently-shaped answer to a caller that trusted the declaration.

Three of the five recipes ask a fixed question and so declare no parameters. That is a fact about
the questions, not a gap — and `tests/unit/test_recipe_contracts.py` checks the declaration and
the SQL agree *in both directions*, so a recipe that references `$root_element_id` without
declaring it fails, and so does one that declares a parameter its SQL never uses.

**The one recursive recipe is bounded, and that is not optional.** Measured against DataFusion
54.0.0: a bounded `WITH RECURSIVE` over a cyclic `contains` edge set terminates and returns the
truncated walk; the same query without the depth guard had not terminated after fifteen seconds.
`contains` declares the `acyclic` validation rule, but a model that failed validation can still be
published by a caller that ignored the diagnostics, so the bound is what makes the recipe safe on
data rather than on trust.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal

import pyarrow as pa
from pydantic import Field

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import (
    PolicyId,
    QueryRecipeId,
    SchemaVersion,
    TableId,
)
from architecture_toolkit.queries.errors import ParameterError, UnknownRecipeError
from architecture_toolkit.queries.sides import Side
from architecture_toolkit.storage.schemas import TABLE_IDS

__all__ = [
    "RECIPES",
    "ColumnSpec",
    "ParameterSpec",
    "QueryRecipe",
    "ReleaseContextKind",
    "ScalarType",
    "TableInput",
    "bind_parameters",
    "declared_schema",
    "recipe_for",
]

ScalarType = Literal["string", "integer", "boolean", "instant", "day"]
"""The result vocabulary, deliberately the same five scalars `storage/schemas.py` persists.

`BASELINE_TYPES` is the persisted set; a recipe that returned a sixth would be introducing a type
to the toolkit through a query rather than through a schema.
"""

ReleaseContextKind = Literal["single", "comparison"]

_ARROW: Final[Mapping[ScalarType, pa.DataType]] = MappingProxyType(
    {
        "string": pa.string(),
        "integer": pa.int64(),
        "boolean": pa.bool_(),
        "instant": pa.timestamp("us", tz="UTC"),
        "day": pa.date32(),
    }
)

_PYTHON: Final[Mapping[ScalarType, type]] = MappingProxyType(
    {"string": str, "integer": int, "boolean": bool}
)
"""What a bound parameter must be. Timestamps and dates are not accepted as parameters yet; no
recipe needs one, and accepting a `datetime` would mean deciding a timezone policy nothing asks
for."""


class ParameterSpec(CompiledRecord):
    """One runtime scalar, bound as `$name` (DATA-18)."""

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    data_type: ScalarType
    required: bool = True
    purpose: str = Field(min_length=1)

    @property
    def placeholder(self) -> str:
        return f"${self.name}"


class ColumnSpec(CompiledRecord):
    """One column of a recipe's declared result."""

    name: str = Field(min_length=1)
    data_type: ScalarType
    nullable: bool = True


class TableInput(CompiledRecord):
    """A table this recipe reads, and which side it reads it from (DATA-47).

    `side` is `None` for a single-release recipe. A comparison recipe names its sides explicitly
    so the declaration says which release each input comes from, rather than leaving a reader to
    infer it from the SQL.
    """

    table_id: TableId
    side: Side | None = None


class QueryRecipe(CompiledRecord):
    """A versioned architecture question with a declared parameter and result contract."""

    query_recipe_id: QueryRecipeId
    query_recipe_version: SchemaVersion
    purpose: str = Field(min_length=1)
    release_context: ReleaseContextKind
    inputs: tuple[TableInput, ...] = Field(min_length=1)
    parameters: tuple[ParameterSpec, ...] = ()
    output_schema: tuple[ColumnSpec, ...] = Field(min_length=1)
    sql: str = Field(min_length=1)
    traversal_policy_id: PolicyId | None = None
    """The graph policy whose semantics this recipe's answer corresponds to, where one exists.

    Only the traversal recipes in `queries/policy.py` set this. A relational recipe has no
    traversal semantics and says so by leaving it unset, rather than by omitting the field."""
    qualification_cases: tuple[str, ...] = Field(min_length=1)

    @property
    def is_recursive(self) -> bool:
        return "WITH RECURSIVE" in self.sql.upper()


def declared_schema(recipe: QueryRecipe) -> pa.Schema:
    """The Arrow schema the recipe promises, as a schema rather than as a description."""
    return pa.schema(
        [
            pa.field(column.name, _ARROW[column.data_type], nullable=column.nullable)
            for column in recipe.output_schema
        ]
    )


def bind_parameters(
    recipe: QueryRecipe, parameters: Mapping[str, object] | None
) -> dict[str, object]:
    """Check supplied parameters against the declared schema, and return what to bind.

    `bool` is checked before `int` because `bool` is a subclass of `int` in Python, so `True`
    would otherwise satisfy an `integer` parameter and be bound as `1` — a silent coercion in a
    depth bound is exactly the kind of thing that is discovered much later.
    """
    supplied = dict(parameters or {})
    declared = {spec.name: spec for spec in recipe.parameters}

    unknown = sorted(set(supplied) - set(declared))
    if unknown:
        message = f"{recipe.query_recipe_id} does not declare parameter(s) {unknown}"
        raise ParameterError(message)

    bound: dict[str, object] = {}
    for name, spec in declared.items():
        if name not in supplied:
            if spec.required:
                message = f"{recipe.query_recipe_id} requires parameter {name!r}: {spec.purpose}"
                raise ParameterError(message)
            continue
        value = supplied[name]
        expected = _PYTHON[spec.data_type]
        if type(value) is not expected:
            message = (
                f"{recipe.query_recipe_id} parameter {name!r} must be {spec.data_type}, "
                f"got {type(value).__name__}"
            )
            raise ParameterError(message)
        bound[name] = value
    return bound


def recipe_for(query_recipe_id: str) -> QueryRecipe:
    try:
        return RECIPES[query_recipe_id]
    except KeyError:
        message = f"unknown query recipe {query_recipe_id!r}; choose one of {sorted(RECIPES)}"
        raise UnknownRecipeError(message) from None


def _single(*table_ids: TableId) -> tuple[TableInput, ...]:
    return tuple(TableInput(table_id=table_id) for table_id in table_ids)


def _sided(side: Side, *table_ids: TableId) -> tuple[TableInput, ...]:
    return tuple(TableInput(table_id=table_id, side=side) for table_id in table_ids)


_REQUIREMENTS_WITHOUT_VERIFICATION = QueryRecipe(
    query_recipe_id="requirements_without_verification",
    query_recipe_version="1.0.0",
    purpose=(
        "Requirements whose verification method has not been established. DATA-41: this is an "
        "evidence gap to report, not a hole to fill so a coverage report looks complete."
    ),
    release_context="single",
    inputs=_single("requirement_details", "elements"),
    output_schema=(
        ColumnSpec(name="element_id", data_type="string", nullable=False),
        ColumnSpec(name="name", data_type="string", nullable=False),
        ColumnSpec(name="category", data_type="string", nullable=False),
        ColumnSpec(name="applicability", data_type="string", nullable=False),
    ),
    sql=(
        "SELECT e.element_id, e.name, d.category, d.applicability "
        "FROM requirement_details d "
        "JOIN elements e ON e.element_id = d.element_id "
        "WHERE d.verification_method = 'not_established' "
        "ORDER BY e.element_id"
    ),
    qualification_cases=(
        "a requirement with verification_method=test is absent",
        "a requirement with verification_method=not_established is present",
    ),
)

_INTERFACES_MISSING_REQUEST_SCHEMA = QueryRecipe(
    query_recipe_id="interfaces_missing_request_schema",
    query_recipe_version="1.0.0",
    purpose=(
        "Interfaces that declare no request schema. A synchronous interface with no request "
        "shape is a genuine modelling gap; a null here is that gap, not an absent record."
    ),
    release_context="single",
    inputs=_single("interface_details", "elements"),
    output_schema=(
        ColumnSpec(name="element_id", data_type="string", nullable=False),
        ColumnSpec(name="name", data_type="string", nullable=False),
        ColumnSpec(name="delivery_semantics", data_type="string", nullable=False),
    ),
    sql=(
        "SELECT e.element_id, e.name, d.delivery_semantics "
        "FROM interface_details d "
        "JOIN elements e ON e.element_id = d.element_id "
        "WHERE d.request_schema_id IS NULL "
        "ORDER BY e.element_id"
    ),
    qualification_cases=(
        "an interface declaring a request schema is absent",
        "an interface with a null request schema is present",
    ),
)

_CAPABILITY_COVERAGE_MATRIX = QueryRecipe(
    query_recipe_id="capability_coverage_matrix",
    query_recipe_version="1.0.0",
    purpose=(
        "Every business capability with the number of applications that support or realize it. "
        "A capability with no application is reported with a zero, not omitted: an absent row "
        "would make the uncovered capability invisible, which is the opposite of a coverage "
        "matrix's purpose."
    ),
    release_context="single",
    inputs=_single("elements", "relationships"),
    output_schema=(
        ColumnSpec(name="capability_id", data_type="string", nullable=False),
        ColumnSpec(name="capability_name", data_type="string", nullable=False),
        ColumnSpec(name="application_count", data_type="integer", nullable=False),
        ColumnSpec(name="covered", data_type="boolean", nullable=False),
    ),
    sql=(
        "SELECT cap.element_id AS capability_id, cap.name AS capability_name, "
        "count(app.element_id) AS application_count, "
        "count(app.element_id) > 0 AS covered "
        "FROM elements cap "
        "LEFT JOIN relationships r ON r.target_element_id = cap.element_id "
        "AND r.relationship_type_id IN ('supports', 'realizes') "
        "LEFT JOIN elements app ON app.element_id = r.source_element_id "
        "AND app.kind_id IN ('software.system', 'software.component') "
        "WHERE cap.kind_id = 'business.capability' "
        "GROUP BY cap.element_id, cap.name "
        "ORDER BY cap.element_id"
    ),
    qualification_cases=(
        "a capability supported by one application counts one",
        "a capability with no supporting application is present with a zero",
    ),
)

_OWNERSHIP_ACROSS_RELEASES = QueryRecipe(
    query_recipe_id="application_ownership_across_releases",
    query_recipe_version="1.0.0",
    purpose=(
        "Which role is accountable for each owned element, on each side of a comparison. A full "
        "outer join rather than an inner one, so ownership that appeared or disappeared between "
        "the two releases is visible rather than silently dropped."
    ),
    release_context="comparison",
    inputs=_sided("base", "relationships") + _sided("candidate", "relationships"),
    output_schema=(
        ColumnSpec(name="element_id", data_type="string", nullable=True),
        ColumnSpec(name="base_owner", data_type="string", nullable=True),
        ColumnSpec(name="candidate_owner", data_type="string", nullable=True),
    ),
    sql=(
        "SELECT COALESCE(b.target_element_id, c.target_element_id) AS element_id, "
        "b.source_element_id AS base_owner, c.source_element_id AS candidate_owner "
        "FROM (SELECT source_element_id, target_element_id FROM base.relationships "
        "WHERE relationship_type_id = 'responsible_for') b "
        "FULL OUTER JOIN (SELECT source_element_id, target_element_id "
        "FROM candidate.relationships WHERE relationship_type_id = 'responsible_for') c "
        "ON b.target_element_id = c.target_element_id "
        "ORDER BY 1"
    ),
    qualification_cases=(
        "unchanged ownership reports the same role on both sides",
        "a reassigned owner reports two different roles",
    ),
)
"""No kind filter, deliberately. The baseline profile permits `responsible_for` from a role to a
process, system, component, capability or object, so narrowing to the software kinds would drop
accountability the model actually records and report it as absent."""

_CONTAINMENT_HIERARCHY = QueryRecipe(
    query_recipe_id="containment_hierarchy",
    query_recipe_version="1.0.0",
    purpose=(
        "Everything contained beneath one element, with the relationship that contains it and "
        "the depth at which it sits. Naturally relational and naturally recursive, which is the "
        "case data.md reserves recursive SQL for."
    ),
    release_context="single",
    inputs=_single("relationships", "elements"),
    parameters=(
        ParameterSpec(
            name="root_element_id",
            data_type="string",
            purpose="The element whose contents are wanted.",
        ),
        ParameterSpec(
            name="max_depth",
            data_type="integer",
            purpose=(
                "How far to descend. Required, not defaulted: an unbounded recursion over a "
                "cyclic containment edge set does not terminate."
            ),
        ),
    ),
    output_schema=(
        ColumnSpec(name="element_id", data_type="string", nullable=False),
        ColumnSpec(name="name", data_type="string", nullable=False),
        ColumnSpec(name="relationship_id", data_type="string", nullable=False),
        ColumnSpec(name="depth", data_type="integer", nullable=False),
    ),
    sql=(
        "WITH RECURSIVE descent AS ("
        "SELECT target_element_id AS element_id, relationship_id, 1 AS depth "
        "FROM relationships "
        "WHERE relationship_type_id = 'contains' AND source_element_id = $root_element_id "
        "UNION ALL "
        "SELECT r.target_element_id, r.relationship_id, d.depth + 1 "
        "FROM relationships r JOIN descent d ON r.source_element_id = d.element_id "
        "WHERE r.relationship_type_id = 'contains' AND d.depth < $max_depth"
        ") "
        "SELECT d.element_id, e.name, d.relationship_id, d.depth "
        "FROM descent d JOIN elements e ON e.element_id = d.element_id "
        "ORDER BY d.depth, d.element_id"
    ),
    qualification_cases=(
        "a one-level containment returns the child at depth one",
        "max_depth truncates a deeper hierarchy",
        "a cyclic containment edge set terminates at max_depth",
    ),
)

RECIPES: Final[Mapping[QueryRecipeId, QueryRecipe]] = MappingProxyType(
    {
        recipe.query_recipe_id: recipe
        for recipe in (
            _REQUIREMENTS_WITHOUT_VERIFICATION,
            _INTERFACES_MISSING_REQUEST_SCHEMA,
            _CAPABILITY_COVERAGE_MATRIX,
            _OWNERSHIP_ACROSS_RELEASES,
            _CONTAINMENT_HIERARCHY,
        )
    }
)
"""The initial set `ARCH-TOOL-DATA-001` §4A names, plus the one recursive recipe DATA-15 asks to be
qualified rather than assumed."""


def _check_registry() -> None:
    """Every input names a real table. Run at import, like `validation/codes.py`'s own guard."""
    for recipe in RECIPES.values():
        unknown = sorted({item.table_id for item in recipe.inputs} - set(TABLE_IDS))
        if unknown:
            message = f"{recipe.query_recipe_id} names unknown table(s) {unknown}"
            raise ValueError(message)


_check_registry()
