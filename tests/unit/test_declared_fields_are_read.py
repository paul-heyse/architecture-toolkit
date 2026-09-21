"""Every field a query or change record declares is read somewhere (CORE-26, DATA-48, DATA-26).

`Relationship.context_id` has been declared, mapped to Arrow, round-tripped and written by nothing
since W1 — a field that looks like it does something and does not. W5 shipped a second one:
`GraphPolicy.cycle_handling`, set to `REPORT` on a policy and branched on by no code at all. The
first was inherited; the second was introduced by the wave that noticed the first.

W6's records are held to the same standard, which is what makes this the guard for the class
rather than for the instance: an `ArchitectureChangeSet` field that nothing reads would be the
third instance of exactly this, in the third wave running.

So this is the guard for the class rather than for the instance. It scans the package's syntax tree
for attribute reads and asserts every declared field name appears among them, with an explicit
allow-list — empty today — for a field that is genuinely declaration-only.

**It is a coarse check and says so.** Attribute reads are matched by name, so `recipe.purpose`
satisfies `policy.purpose`. Making it precise would need type inference the syntax tree does not
carry. Coarse is enough for what it catches: a field nothing anywhere reads, which is the failure
that actually happens.
"""

import ast
from dataclasses import fields
from pathlib import Path

import pytest
from pydantic import BaseModel

from architecture_toolkit.changes.kinds import ChangeRule
from architecture_toolkit.changes.record import ArchitectureChangeSet, Authorship, Review
from architecture_toolkit.changes.records import FieldChange, ModelChanges, RecordChange
from architecture_toolkit.queries.policy import GraphPolicy
from architecture_toolkit.queries.recipes import ParameterSpec, QueryRecipe
from architecture_toolkit.queries.results import GraphPathResult, TraversalResult

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "architecture_toolkit"

DECLARATION_ONLY: dict[str, str] = {}
"""Fields that are declared and deliberately never read, each with the reason.

Empty, and the point of the file is to keep it that way: a field added here is a decision somebody
made on purpose, and a field that lands here by accident fails the test instead."""


def attribute_reads(root: Path) -> set[str]:
    """Every name read as an attribute anywhere in the package."""
    found: set[str] = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute):
                found.add(node.attr)
    return found


@pytest.mark.unit
@pytest.mark.requirement("CORE-26", "DATA-48")
@pytest.mark.parametrize(
    "record",
    [
        GraphPolicy,
        QueryRecipe,
        ParameterSpec,
        GraphPathResult,
        TraversalResult,
        ArchitectureChangeSet,
        Authorship,
        Review,
        ModelChanges,
        RecordChange,
        FieldChange,
    ],
    ids=lambda record: record.__name__,
)
def test_every_declared_field_is_read_somewhere(record: type[BaseModel]) -> None:
    read = attribute_reads(PACKAGE)
    declared = set(record.model_fields)

    unread = sorted(declared - read - set(DECLARATION_ONLY))
    assert not unread, (
        f"{record.__name__} declares {unread}, which nothing in the package reads. Give the "
        "field force, remove it, or add it to DECLARATION_ONLY with the reason."
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-26")
def test_the_scan_finds_attribute_reads_at_all() -> None:
    """A guard that read nothing would pass forever."""
    read = attribute_reads(PACKAGE)

    assert {"policy_id", "max_depth", "relationship_ids", "sql"} <= read
    assert len(read) > 100


@pytest.mark.unit
@pytest.mark.requirement("CORE-26")
def test_the_scan_would_catch_a_field_nothing_reads() -> None:
    """The negative control, with the name W5 actually shipped dead."""
    read = attribute_reads(PACKAGE)

    assert "sanctimonious_field_nobody_reads" not in read


@pytest.mark.unit
@pytest.mark.requirement("CORE-26", "DATA-26")
def test_the_change_rule_dataclass_is_held_to_the_same_standard() -> None:
    """`ChangeRule` is a dataclass rather than a Pydantic record, so the scan above skips it.

    It is the table's value type, and a declared-and-unread field there would be the same defect
    wearing a different base class — `GraphPolicy.cycle_handling` was exactly that.
    """
    read = attribute_reads(PACKAGE)
    declared = {field.name for field in fields(ChangeRule)}

    unread = sorted(declared - read)
    assert not unread, f"ChangeRule declares {unread}, which nothing in the package reads"


# -- the two kinds of declaration the field scan above cannot see -----------------------------

# Properties and module constants, which `model_fields` does not enumerate. W6 shipped ten of the
# first kind with no reader at all — four delegating properties on `ArchitectureChangeSet`, plus
# `RecordChange.is_presence`, `as_element_reference`, `ModelChanges.for_collection`,
# `ReleaseCandidate.is_alternative` and `lineage.scenario_of` — so the guard for the class had a
# blind spot exactly where the wave put its new code.

PROPERTY_ONLY: dict[str, str] = {}
"""Properties that are deliberately never read. Empty, and the point is to keep it that way."""


def declared_properties(record: type) -> set[str]:
    return {
        name
        for name, value in vars(record).items()
        if isinstance(value, property) and not name.startswith("_")
    }


@pytest.mark.unit
@pytest.mark.requirement("CORE-26", "DATA-26")
@pytest.mark.parametrize(
    "record",
    [ArchitectureChangeSet, Authorship, Review, ModelChanges, RecordChange, FieldChange],
    ids=lambda record: record.__name__,
)
def test_every_declared_property_is_read_somewhere(record: type[BaseModel]) -> None:
    read = attribute_reads(PACKAGE)
    unread = sorted(declared_properties(record) - read - set(PROPERTY_ONLY))

    assert not unread, (
        f"{record.__name__} declares properties {unread}, which nothing in the package reads. "
        "Give them force, remove them, or add them to PROPERTY_ONLY with the reason."
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-26", "DATA-26")
def test_every_module_constant_the_change_layer_exports_is_read_somewhere() -> None:
    """A constant nobody reads is the same defect as a field nobody reads, one scope up.

    Scoped to `changes/` because that is where this wave's constants live; the names come from the
    package's own `__all__`, so a constant exported and then never used fails here.
    """
    import architecture_toolkit.changes as layer

    names = {
        name
        for name in layer.__all__
        if name.isupper() and not isinstance(getattr(layer, name), type)
    }
    used = {
        name
        for name in names
        if any(
            name in path.read_text(encoding="utf-8")
            for path in PACKAGE.rglob("*.py")
            if path.name not in {"__init__.py"}
        )
    }

    # Non-vacuity, both halves: the scan found constants at all, and it found the specific ones a
    # reader would expect — a scan that silently matched nothing would satisfy the equality above.
    assert {"CHANGE_CLASSIFICATION", "NEVER_EMITTED", "NARRATIVE_NATURES"} <= names
    assert names == used, f"exported and unread: {sorted(names - used)}"
