"""Row-local persisted invariants, and the boundary around them (DATA-55).

`ARCH-TOOL-DATA-001` §11G draws the line and names what is on the far side of it: relationship
endpoint validity, cross-table referential rules, graph and cardinality semantics, evidence and
approval requirements, and architecture-release consistency. None of those can be a Delta check
constraint, because a check constraint is a predicate over one row and every one of them needs
context that one row does not contain.

What *is* row-local is narrow, and that is the point. A digest is well-formed or it is not. A
timeout is nonnegative or it is not. Neither needs to know another row exists.

**Applied as a deliberate maintenance operation, not during publication.** Adding a constraint is
a Delta commit, so doing it inside publication would put a second commit on the tail of every
newly created table and make the version a manifest pins depend on whether the table happened to
be new. Publication's version arithmetic should be boring; `apply_constraints` is a separate call
that says what it is doing.

The guard that matters is not that these constraints exist — it is that nothing cross-record ever
joins them. `tests/unit/test_constraint_boundary.py` asserts every declared predicate mentions
only columns of its own table.
"""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.schemas import TABLE_IDS, TABLE_SCHEMAS

__all__ = [
    "ROW_LOCAL_CONSTRAINTS",
    "apply_constraints",
    "columns_of",
    "declared_constraints",
]

_DIGEST_SHAPE = "content_hash LIKE 'sha256:%'"

ROW_LOCAL_CONSTRAINTS: Final[Mapping[TableId, Mapping[str, str]]] = MappingProxyType(
    {
        **{
            table_id: MappingProxyType({"content_hash_is_a_sha256_digest": _DIGEST_SHAPE})
            for table_id in TABLE_IDS
        },
        "interface_details": MappingProxyType(
            {
                "content_hash_is_a_sha256_digest": _DIGEST_SHAPE,
                # Nullable, and a null passes a Delta check constraint — which is correct here:
                # "no timeout stated" and "a negative timeout" are different claims and only the
                # second is impossible.
                "timeout_ms_is_not_negative": "timeout_ms IS NULL OR timeout_ms >= 0",
            }
        ),
    }
)
"""Every persisted invariant that needs only the row it is about. Deliberately short."""


def declared_constraints(table_id: TableId) -> Mapping[str, str]:
    return ROW_LOCAL_CONSTRAINTS.get(table_id, {})


def apply_constraints(location: Path, table_id: TableId, *, version: int) -> Mapping[str, str]:
    """Attach this table's row-local constraints, and report what it now carries.

    Idempotent in the way that matters: Delta refuses to add a constraint that already exists, so
    only the missing ones are added.
    """
    existing = delta.constraints(location, version=version)
    missing = {
        name: predicate
        for name, predicate in declared_constraints(table_id).items()
        if name not in existing
    }
    if missing:
        delta.add_constraints(location, version=version, expressions=missing)
        version = delta.tip(location)
    return delta.constraints(location, version=version)


def columns_of(table_id: TableId) -> frozenset[str]:
    """The column names a predicate for this table may mention."""
    return frozenset(TABLE_SCHEMAS[table_id].bare().names)
