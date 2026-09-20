"""The only module that reads or writes Arrow metadata (DATA-44).

DATA-44 asks that a persisted table describe itself. The risk in doing that is subtle and worth
naming: once a table carries metadata saying what it is, the temptation is to read that metadata
to decide what to do with it, and then the meaning of the data lives in a place that Delta drops
on the way through. **Metadata here is self-description and never semantics.** Nothing outside
this module reads `.metadata`, `tests/unit/test_metadata_policy.py` scans for that, and
`tests/unit/test_storage_mappings.py` asserts that a table stripped of all metadata produces
identical records and identical digests.

Delta preserves **field-level** metadata and **drops schema-level** metadata — measured, not
assumed. So a table read back from Delta has lost the four schema keys and kept every field role,
and `reattach` is what a reader does about it: cast to the declared bare schema, which restores
nullability and field metadata that `set_column` and friends drop, then put the schema keys back.
The compatibility matrix pins the asymmetry so a deltalake release that starts preserving
schema-level metadata is noticed rather than silently relied on.
"""

from importlib.metadata import version
from typing import Final

import pyarrow as pa

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.storage.schemas import (
    ROLE_KEY,
    STORAGE_SCHEMA_VERSION,
    TableRole,
    TableSchema,
)

__all__ = [
    "NAMESPACE",
    "SCHEMA_KEYS",
    "SchemaDescription",
    "describe",
    "field_roles",
    "read_description",
    "reattach",
    "strip",
    "toolkit_version",
]

NAMESPACE: Final[str] = "architecture_toolkit"

_STORAGE_SCHEMA_VERSION_KEY: Final[bytes] = b"architecture_toolkit.storage_schema_version"
_TABLE_ID_KEY: Final[bytes] = b"architecture_toolkit.table_id"
_TABLE_ROLE_KEY: Final[bytes] = b"architecture_toolkit.table_role"
_TOOLKIT_VERSION_KEY: Final[bytes] = b"architecture_toolkit.toolkit_version"

SCHEMA_KEYS: Final[tuple[bytes, ...]] = (
    _STORAGE_SCHEMA_VERSION_KEY,
    _TABLE_ID_KEY,
    _TABLE_ROLE_KEY,
    _TOOLKIT_VERSION_KEY,
)


def toolkit_version() -> str:
    """The installed distribution version, so a table records what wrote it."""
    return version("architecture-toolkit")


class SchemaDescription(CompiledRecord):
    """What a table's metadata says about itself.

    A claim, never an instruction. A table whose metadata says `table_id="elements"` is read
    through the `elements` mapping because the *caller* asked for `elements`, not because the
    metadata said so — otherwise a mislabelled table would be silently read the wrong way.
    """

    storage_schema_version: str | None = None
    table_id: str | None = None
    table_role: TableRole | None = None
    toolkit_version: str | None = None


def describe(schema: pa.Schema, *, table_id: str, role: TableRole) -> pa.Schema:
    """`schema` with the four self-description keys attached at schema level."""
    existing = schema.metadata or {}
    return schema.with_metadata(
        {
            **existing,
            _STORAGE_SCHEMA_VERSION_KEY: STORAGE_SCHEMA_VERSION.encode(),
            _TABLE_ID_KEY: table_id.encode(),
            _TABLE_ROLE_KEY: role.value.encode(),
            _TOOLKIT_VERSION_KEY: toolkit_version().encode(),
        }
    )


def strip(schema: pa.Schema) -> pa.Schema:
    """`schema` with every `architecture_toolkit.*` key removed, at schema and field level.

    Used by the guard that proves metadata carries no meaning: strip it and the records and
    digests must be unchanged.
    """
    return pa.schema(
        [pa.field(f.name, f.type, nullable=f.nullable) for f in schema],
        metadata={
            key: value
            for key, value in (schema.metadata or {}).items()
            if not key.startswith(NAMESPACE.encode())
        }
        or None,
    )


def read_description(schema: pa.Schema) -> SchemaDescription:
    """Read the four keys back. Absent keys are `None` — Delta drops them all."""
    metadata = schema.metadata or {}

    def text(key: bytes) -> str | None:
        raw = metadata.get(key)
        return raw.decode() if raw is not None else None

    role = text(_TABLE_ROLE_KEY)
    return SchemaDescription(
        storage_schema_version=text(_STORAGE_SCHEMA_VERSION_KEY),
        table_id=text(_TABLE_ID_KEY),
        table_role=TableRole(role) if role is not None else None,
        toolkit_version=text(_TOOLKIT_VERSION_KEY),
    )


def field_roles(schema: pa.Schema) -> dict[str, str]:
    """Each top-level field's declared role. Survives a Delta round trip; still not semantics."""
    return {
        f.name: f.metadata[ROLE_KEY].decode()
        for f in schema
        if f.metadata and ROLE_KEY in f.metadata
    }


def reattach(table: pa.Table, expected: TableSchema) -> pa.Table:
    """Restore a read table to its declared schema, metadata included.

    Two losses are repaired at once. `cast` to the bare declared schema restores nullability and
    field metadata, which `Table.set_column` drops and which a Delta read may reorder or relax;
    `replace_schema_metadata` puts back the schema-level keys Delta drops entirely.
    """
    cast = table.cast(expected.bare())
    described = describe(expected.schema, table_id=expected.table_id, role=expected.role)
    return cast.cast(described)
