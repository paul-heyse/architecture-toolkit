"""Arrow metadata is self-description and never semantics (DATA-44)."""

import ast
from pathlib import Path

import pyarrow as pa
import pytest

from architecture_toolkit.storage import metadata
from architecture_toolkit.storage.metadata import (
    NAMESPACE,
    SCHEMA_KEYS,
    describe,
    field_roles,
    read_description,
    reattach,
    strip,
)
from architecture_toolkit.storage.schemas import STORAGE_SCHEMA_VERSION, TABLE_SCHEMAS, TableRole

SRC = Path(__file__).resolve().parents[2] / "src" / "architecture_toolkit"

# The names that read or write Arrow metadata. `importlib.metadata` is excluded by matching on
# the attribute of a value rather than on a module path — see `_metadata_access`.
METADATA_NAMES = frozenset(
    {"metadata", "with_metadata", "remove_metadata", "replace_schema_metadata"}
)


def _metadata_access(source: str) -> set[str]:
    """Attribute reads and calls that touch **Arrow** metadata.

    Two exclusions, both because the name is overloaded rather than because the rule is being
    relaxed. `importlib.metadata` is a module reference. `DeltaTable(...).metadata()` is Delta
    *table* metadata — name, description and configuration, which is where Delta keeps its check
    constraints — and has nothing to do with the Arrow schema and field metadata DATA-44 governs.
    Neither can become hidden semantic authority over a model, which is what the rule protects.
    """
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in METADATA_NAMES:
            continue
        if isinstance(node.value, ast.Name) and node.value.id == "importlib":
            continue
        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "DeltaTable"
        ):
            continue
        found.add(node.attr)
    return found


@pytest.mark.unit
@pytest.mark.requirement("DATA-44")
def test_the_scan_catches_a_known_bad_reading() -> None:
    assert _metadata_access("def f(schema):\n    return schema.metadata\n") == {"metadata"}
    assert _metadata_access("def f(t, m):\n    return t.replace_schema_metadata(m)\n") == {
        "replace_schema_metadata"
    }
    assert _metadata_access("import importlib\nx = importlib.metadata\n") == set()
    assert _metadata_access("def f(schema):\n    return schema.names\n") == set()
    # Delta table metadata is a different thing wearing the same name, and the exclusion is
    # narrow enough that a bare `.metadata` on anything else is still caught.
    assert _metadata_access("c = DeltaTable(loc, version=0).metadata().configuration") == set()
    assert _metadata_access("c = dt.metadata().configuration") == {"metadata"}


@pytest.mark.unit
@pytest.mark.requirement("DATA-44")
def test_only_the_metadata_module_touches_arrow_metadata() -> None:
    """One reader, so a table's meaning cannot come to depend on what Delta drops.

    Delta preserves field-level metadata and drops schema-level metadata. If any module read
    metadata to decide behaviour, that behaviour would change on the way through storage.
    """
    allowed = SRC / "storage" / "metadata.py"
    offenders = {
        path.relative_to(SRC).as_posix(): sorted(_metadata_access(path.read_text()))
        for path in SRC.rglob("*.py")
        if path != allowed
    }
    leaked = {path: names for path, names in offenders.items() if names}
    assert not leaked, f"Arrow metadata touched outside storage/metadata.py: {leaked}"


@pytest.mark.unit
@pytest.mark.requirement("DATA-44")
def test_a_described_schema_says_what_it_is() -> None:
    declared = TABLE_SCHEMAS["elements"]
    described = describe(declared.bare(), table_id="elements", role=TableRole.ENTITY)
    read = read_description(described)
    assert read.table_id == "elements"
    assert read.table_role is TableRole.ENTITY
    assert read.storage_schema_version == STORAGE_SCHEMA_VERSION
    assert read.toolkit_version == metadata.toolkit_version()
    assert set(SCHEMA_KEYS) <= set(described.metadata or {})


@pytest.mark.unit
@pytest.mark.requirement("DATA-44")
def test_an_undescribed_schema_reads_back_as_all_none() -> None:
    """What a Delta read looks like: field metadata kept, every schema-level key gone."""
    read = read_description(TABLE_SCHEMAS["elements"].bare())
    assert read.storage_schema_version is None
    assert read.table_id is None
    assert read.table_role is None
    assert read.toolkit_version is None


@pytest.mark.unit
@pytest.mark.requirement("DATA-44")
def test_strip_removes_every_toolkit_key_at_both_levels() -> None:
    declared = TABLE_SCHEMAS["elements"]
    described = describe(declared.schema, table_id="elements", role=TableRole.ENTITY)
    stripped = strip(described)
    assert stripped.metadata is None
    assert all(field.metadata is None for field in stripped)
    assert not any(key.startswith(NAMESPACE.encode()) for key in (stripped.metadata or {}))
    # Types and nullability are untouched: stripping metadata is not stripping the schema.
    assert stripped.names == declared.schema.names
    assert [f.type for f in stripped] == [f.type for f in declared.schema]


@pytest.mark.unit
@pytest.mark.requirement("DATA-44")
def test_reattach_restores_what_a_delta_read_loses() -> None:
    """Cast restores nullability and field roles; replace restores the schema-level keys."""
    declared = TABLE_SCHEMAS["deployment_details"]
    as_delta_returns_it = pa.Table.from_pylist(
        [
            {
                "element_id": "elt-1",
                "environment": "prod",
                "deployment_node_id": None,
                "software_instance_id": None,
                "configuration_artifact_id": None,
                "content_hash": "sha256:" + "0" * 64,
            }
        ],
        schema=strip(declared.bare()),
    )
    assert read_description(as_delta_returns_it.schema).table_id is None
    assert field_roles(as_delta_returns_it.schema) == {}

    restored = reattach(as_delta_returns_it, declared)
    assert read_description(restored.schema).table_id == "deployment_details"
    assert field_roles(restored.schema)["element_id"] == "identity"
    # `TableSchema.schema` carries field roles and no schema-level keys: the description is
    # added when a table is written, because it names the toolkit version that wrote it and
    # `schemas.py` cannot import `metadata.py` without a cycle.
    expected = describe(declared.schema, table_id="deployment_details", role=TableRole.DETAIL)
    assert restored.schema.equals(expected, check_metadata=True)
    assert restored.to_pylist() == as_delta_returns_it.to_pylist()
