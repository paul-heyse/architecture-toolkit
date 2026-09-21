"""The DataFusion 54 behaviours W5 relies on, qualified rather than assumed (DATA-15, DATA-18).

`data.md` says recursive CTEs are used "selectively", and the W5 plan says to fall back to NetworkX
if the pinned runtime does not support them. It does — which is a fact that had to be measured, and
which is measured here rather than inferred from the version number.

**The finding that shaped the recipe.** A bounded `WITH RECURSIVE` over a cyclic `contains` edge set
terminates and returns the truncated walk. The same query with the depth guard removed had not
terminated after fifteen seconds when it was measured by hand. That second half is deliberately not
a test: a suite must not contain a query that may never return, and a timeout assertion would be a
flaky proxy for a fact that is not in doubt. It is why
`queries/recipes.py::_CONTAINMENT_HIERARCHY` declares `max_depth` **required**, and
`tests/unit/test_recipe_contracts.py` is where that consequence is enforced for every future
recursive recipe.
"""

import pyarrow as pa
import pytest
from datafusion import SessionContext, SQLOptions

from architecture_toolkit.queries.context import read_only_options, session_config

CYCLE = pa.table(
    {
        "source_element_id": ["a", "b", "c"],
        "target_element_id": ["b", "c", "a"],
        "relationship_type_id": ["contains"] * 3,
    }
)
CHAIN = pa.table(
    {
        "source_element_id": ["a", "b"],
        "target_element_id": ["b", "c"],
        "relationship_type_id": ["contains"] * 2,
    }
)
DESCENT = (
    "WITH RECURSIVE descent AS ("
    "SELECT target_element_id AS element_id, 1 AS depth FROM relationships "
    "WHERE relationship_type_id = 'contains' AND source_element_id = $root "
    "UNION ALL "
    "SELECT r.target_element_id, d.depth + 1 FROM relationships r "
    "JOIN descent d ON r.source_element_id = d.element_id "
    "WHERE r.relationship_type_id = 'contains' AND d.depth < $max_depth"
    ") SELECT element_id, depth FROM descent ORDER BY depth"
)


def context_over(table: pa.Table) -> SessionContext:
    session = SessionContext(session_config())
    session.register_record_batches("relationships", [table.to_batches()])
    return session


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-15")
def test_a_recursive_cte_walks_an_acyclic_hierarchy_to_the_end() -> None:
    session = context_over(CHAIN)

    rows = (
        session.sql_with_options(
            DESCENT, read_only_options(), param_values={"root": "a", "max_depth": 10}
        )
        .to_arrow_table()
        .to_pylist()
    )

    assert rows == [{"element_id": "b", "depth": 1}, {"element_id": "c", "depth": 2}]


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-15", "DATA-18")
def test_a_bounded_recursion_terminates_on_a_cyclic_edge_set() -> None:
    """The reason the depth bound is a required parameter rather than a default.

    Containment declares the `acyclic` validation rule, so a published model should not contain
    this shape — but "should not" is a statement about validation, and this recipe has to be safe
    on data.
    """
    session = context_over(CYCLE)

    rows = (
        session.sql_with_options(
            DESCENT, read_only_options(), param_values={"root": "a", "max_depth": 4}
        )
        .to_arrow_table()
        .to_pylist()
    )

    assert [row["depth"] for row in rows] == [1, 2, 3, 4]
    assert rows[-1]["element_id"] == "b", "the walk revisited the cycle rather than stopping early"


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-18")
@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        ("CREATE TABLE t AS SELECT * FROM relationships", "DDL not supported"),
        ("INSERT INTO relationships SELECT * FROM relationships", "DML not supported"),
        ("DROP TABLE relationships", "DDL not supported"),
        ("SET datafusion.execution.batch_size = 1", "Statement not supported"),
    ],
)
def test_the_planner_refuses_mutation_under_read_only_options(statement: str, reason: str) -> None:
    """DATA-18 is a `SQLOptions` configuration, so the refusal names the planning stage."""
    session = context_over(CHAIN)

    with pytest.raises(Exception, match=reason):
        session.sql_with_options(statement, read_only_options()).collect()


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-18")
def test_the_option_builders_mutate_in_place() -> None:
    """Why `read_only_options()` is a function and not a module constant.

    `with_allow_ddl` returns `self` rather than a new object, so a shared instance would be a
    mutable global any caller could re-enable DDL on. When upstream makes these builders return a
    copy, this fails and the function can become a constant.
    """
    options = SQLOptions()

    assert options.with_allow_ddl(False) is options


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-49")
def test_pinning_target_partitions_removes_the_host_cpu_count_from_the_plan() -> None:
    """Without this a physical plan is a property of the machine, not of the query."""
    pinned = context_over(CHAIN)
    unpinned = SessionContext()
    unpinned.register_record_batches("relationships", [CHAIN.to_batches()])
    query = "SELECT relationship_type_id, count(*) AS n FROM relationships GROUP BY 1"

    assert "RepartitionExec" not in pinned.sql(query).execution_plan().display_indent()
    assert "RepartitionExec" in unpinned.sql(query).execution_plan().display_indent()
