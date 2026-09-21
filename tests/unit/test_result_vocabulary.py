"""Reachability is never reported as certain failure (CORE-28, DATA-17) — policy only.

> do not equate reachability with certain failure
> — DATA-17

This is a constraint on what the toolkit is permitted to *claim*, so it is guarded rather than
implemented. The vocabulary is closed and small; the assertion is that no member of it — name,
value, or the prose documenting it — ever acquires a word that turns "these things are connected"
into "these things will break".

The docstrings are read out of the source with `ast` rather than from the objects, because a
string literal following an enum member is not retained at run time. A guard that could only see
the member names would miss the place the claim would most plausibly creep in.
"""

import ast
from pathlib import Path

import pytest

from architecture_toolkit.queries.policy import POLICIES
from architecture_toolkit.queries.results import (
    GraphPathResult,
    PathClassification,
    TraversalResult,
)

SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "architecture_toolkit" / "queries" / "results.py"
)

CERTAINTY = frozenset(
    {
        "break",
        "breaks",
        "broken",
        "certain",
        "certainly",
        "definitely",
        "fail",
        "fails",
        "failure",
        "guaranteed",
        "must",
        "will",
    }
)
"""Words that turn a traversal into a prediction. `queries/results.py` may not use any of them of
its classifications; the module docstring and the record docstrings are free to, and do, because
explaining the prohibition requires naming it."""


def classification_prose() -> dict[str, str]:
    """Each member's name, value and its following docstring, as one string per member."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    declaration = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PathClassification"
    )
    prose: dict[str, str] = {}
    pending: str | None = None
    for statement in declaration.body:
        if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name):
            pending = statement.targets[0].id
            prose[pending] = pending
        elif (
            pending is not None
            and isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            prose[pending] = f"{prose[pending]} {statement.value.value}"
    return prose


@pytest.mark.unit
@pytest.mark.requirement("CORE-28", "DATA-17")
def test_the_guard_can_see_every_member_and_its_documentation() -> None:
    """A guard that read nothing would pass forever.

    This is what makes the scan below mean something: it proves there is prose to scan.
    """
    prose = classification_prose()

    assert set(prose) == {member.name for member in PathClassification}
    assert all(len(text.split()) > 3 for text in prose.values()), (
        "every classification is documented, or the certainty scan below has nothing to scan"
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-28", "DATA-17")
@pytest.mark.parametrize("member", sorted(member.name for member in PathClassification))
def test_no_classification_claims_a_consequence(member: str) -> None:
    text = classification_prose()[member]
    words = {word.strip(".,;:`'\"()").lower() for word in text.split()}

    offending = sorted(words & CERTAINTY)
    assert not offending, (
        f"PathClassification.{member} says {offending}; a traversal reports what is connected, "
        "not what will happen"
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-28")
def test_a_path_result_cannot_be_constructed_without_its_relationship_ids() -> None:
    """CORE-28: no impact result may discard the path that justifies it."""
    required = {name for name, field in GraphPathResult.model_fields.items() if field.is_required()}

    assert {"node_ids", "relationship_ids", "relationship_types"} <= required
    assert {"release_id", "policy_id", "policy_version"} <= required


@pytest.mark.unit
@pytest.mark.requirement("CORE-29")
def test_a_traversal_result_can_say_it_was_capped() -> None:
    """A silently truncated answer that looked complete would be worse than a slow query."""
    fields = TraversalResult.model_fields

    assert "truncated" in fields
    assert "limit_reached" in fields


@pytest.mark.unit
@pytest.mark.requirement("CORE-26", "DATA-17")
@pytest.mark.parametrize("policy_id", sorted(POLICIES))
def test_every_shipped_policy_classifies_its_answers_from_the_closed_vocabulary(
    policy_id: str,
) -> None:
    assert POLICIES[policy_id].classification in set(PathClassification)
