"""The declared Arrow schemas, and the invariants that make them a contract (DATA-10..DATA-12)."""

from collections.abc import Iterator

import pyarrow as pa
import pytest

from architecture_toolkit.domain.details import ElementDetail
from architecture_toolkit.domain.registry import DetailFamily
from architecture_toolkit.domain.semantics import MODEL_COLLECTIONS
from architecture_toolkit.storage.errors import UnknownTableError
from architecture_toolkit.storage.schemas import (
    BASELINE_TYPES,
    DETAIL_TABLE_BY_FAMILY,
    ROLE_KEY,
    STORAGE_SCHEMA_VERSION,
    TABLE_IDS,
    TABLE_SCHEMAS,
    FieldRole,
    TableRole,
    TableSchema,
    schema_for,
)

ALL = [TABLE_SCHEMAS[table_id] for table_id in TABLE_IDS]
IDS = list(TABLE_IDS)


def walk(dtype: pa.DataType) -> Iterator[pa.DataType]:
    """Every type in a schema, nested ones included."""
    yield dtype
    for index in range(dtype.num_fields):
        yield from walk(dtype.field(index).type)


def walk_fields(schema: pa.Schema) -> Iterator[pa.Field]:
    def inner(field: pa.Field) -> Iterator[pa.Field]:
        yield field
        for index in range(field.type.num_fields):
            yield from inner(field.type.field(index))

    for field in schema:
        yield from inner(field)


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_the_registry_holds_exactly_the_declared_tables() -> None:
    assert list(TABLE_SCHEMAS) == IDS
    assert len(set(IDS)) == len(IDS)
    assert schema_for("elements") is TABLE_SCHEMAS["elements"]
    with pytest.raises(UnknownTableError):
        schema_for("no_such_table")


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_the_independent_collections_come_before_the_details_in_model_field_order() -> None:
    """`TABLE_IDS` order is what W4 pins digests in, so it is asserted rather than assumed.

    Stated as three properties that each cross-check two registries, rather than as the two
    magic numbers this used to hold (`roles[6:] == [DETAIL] * 5`). A literal count is a
    transcription: it has to be re-derived by hand every time a collection or a detail family
    arrives, and it says nothing about *which* tables are where.

    The last assertion is deliberately a **prefix** match. A table may legitimately exist one
    commit ahead of the `Model` field it will carry — that is how a new collection lands without
    breaking `queries/recipes.py`'s import-time registry check, which rejects a recipe input
    naming a table that does not exist yet. A collection with no table still fails.
    """
    roles = [TABLE_SCHEMAS[table_id].role for table_id in TABLE_IDS]
    details = [t for t, r in zip(TABLE_IDS, roles, strict=True) if r is TableRole.DETAIL]
    independent = [t for t, r in zip(TABLE_IDS, roles, strict=True) if r is not TableRole.DETAIL]

    assert details, "no detail table was found; the split stopped meaning anything"
    assert list(TABLE_IDS[len(TABLE_IDS) - len(details) :]) == details
    assert set(details) == set(DETAIL_TABLE_BY_FAMILY.values())
    assert [name for name, _ in MODEL_COLLECTIONS] == independent[: len(MODEL_COLLECTIONS)]


@pytest.mark.unit
@pytest.mark.requirement("DATA-12")
@pytest.mark.parametrize("table", ALL, ids=IDS)
def test_only_the_baseline_types_appear_anywhere(table: TableSchema) -> None:
    """No union, extension, dictionary, `large_*` or non-UTC-microsecond timestamp, at any depth.

    Each is excluded for its own measured reason: a union changes physical layout when a variant
    is added, a dictionary breaks `Table.equals` and reads back as plain string through Delta,
    and a non-microsecond or naive timestamp does not survive the Delta round trip unchanged.
    """
    for dtype in (t for field in table.schema for t in walk(field.type)):
        if pa.types.is_list(dtype) or pa.types.is_struct(dtype):
            continue
        assert dtype in BASELINE_TYPES, f"{table.table_id}: {dtype} is not a baseline type"
        assert not pa.types.is_dictionary(dtype)
        assert not pa.types.is_union(dtype)
        assert not pa.types.is_large_list(dtype)
        assert not pa.types.is_large_string(dtype)
        if pa.types.is_timestamp(dtype):
            assert dtype.unit == "us"
            assert dtype.tz == "UTC"


@pytest.mark.unit
@pytest.mark.requirement("DATA-10", "DATA-41")
@pytest.mark.parametrize("table", ALL, ids=IDS)
def test_every_list_and_every_list_item_is_non_null(table: TableSchema) -> None:
    """An empty collection is `[]`, never null.

    "No aliases" and "we do not know the aliases" are different statements, and DATA-41 requires
    the second to be said with a status rather than with a null.
    """
    for field in walk_fields(table.schema):
        if pa.types.is_list(field.type):
            assert not field.nullable, f"{table.table_id}.{field.name} list is nullable"
            item = field.type.field(0)
            assert item.name == "element", "Delta renames list items to `element` on read"
            assert not item.nullable


@pytest.mark.unit
@pytest.mark.requirement("DATA-12")
@pytest.mark.parametrize("table", ALL, ids=IDS)
def test_the_baseline_persists_no_nullable_struct(table: TableSchema) -> None:
    """DataFusion 54 returns a non-nullable child's default rather than NULL under a null parent.

    The rule that cannot go wrong is to persist no nullable struct at all. The next test states
    the conditional rule that applies if one is ever added.
    """
    nullable_structs = [
        field.name
        for field in walk_fields(table.schema)
        if pa.types.is_struct(field.type) and field.nullable
    ]
    assert not nullable_structs, f"{table.table_id}: {nullable_structs}"


@pytest.mark.unit
@pytest.mark.requirement("DATA-12")
@pytest.mark.parametrize("table", ALL, ids=IDS)
def test_every_child_of_a_nullable_struct_is_nullable(table: TableSchema) -> None:
    """Vacuous today by the test above, and that is the point: it stops being vacuous the moment
    somebody adds a nullable struct, and it fails unless they make its children nullable."""
    for field in walk_fields(table.schema):
        if pa.types.is_struct(field.type) and field.nullable:
            children = [field.type.field(i) for i in range(field.type.num_fields)]
            assert all(child.nullable for child in children), field.name


@pytest.mark.unit
@pytest.mark.requirement("DATA-44")
@pytest.mark.parametrize("table", ALL, ids=IDS)
def test_every_top_level_field_declares_a_role(table: TableSchema) -> None:
    for field in table.schema:
        metadata = field.metadata or {}
        assert ROLE_KEY in metadata, f"{table.table_id}.{field.name} declares no role"
        FieldRole(metadata[ROLE_KEY].decode())


@pytest.mark.unit
@pytest.mark.requirement("DATA-10", "DATA-45")
@pytest.mark.parametrize("table", ALL, ids=IDS)
def test_content_hash_is_the_last_column_and_is_never_null(table: TableSchema) -> None:
    last = table.schema.field(len(table.schema) - 1)
    assert last.name == "content_hash"
    assert not last.nullable
    assert (last.metadata or {})[ROLE_KEY] == FieldRole.DIGEST.value.encode()


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
@pytest.mark.parametrize("table", ALL, ids=IDS)
def test_key_fields_exist_and_are_non_null_identities(table: TableSchema) -> None:
    assert table.key_fields
    for name in table.key_fields:
        field = table.schema.field(name)
        assert not field.nullable
        assert (field.metadata or {})[ROLE_KEY] == FieldRole.IDENTITY.value.encode()


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_detail_tables_carry_no_model_id() -> None:
    """They are in bijection with one model's detail records; the element table holds the scope."""
    for table_id, table in TABLE_SCHEMAS.items():
        if table.role is TableRole.DETAIL:
            assert "model_id" not in table.schema.names, table_id
        else:
            assert "model_id" in table.schema.names, table_id


@pytest.mark.unit
@pytest.mark.requirement("DATA-07", "DATA-10")
def test_the_detail_routing_table_covers_exactly_the_element_attachable_families() -> None:
    """The five variants of `ElementDetail`, not the six members of `DetailFamily`.

    `NOTATION` is the sixth family and is an independent table, because its subject may be a
    relationship. A sixth element-attachable family would fail here and in `compile_tables`,
    whose `match` is exhaustive under Pyrefly.
    """
    variants = {
        variant.model_fields["detail_family"].default
        for variant in ElementDetail.__origin__.__args__  # type: ignore[attr-defined]
    }
    assert set(DETAIL_TABLE_BY_FAMILY) == variants
    assert DetailFamily.NOTATION_BINDING not in DETAIL_TABLE_BY_FAMILY
    assert set(DETAIL_TABLE_BY_FAMILY.values()) <= set(TABLE_IDS)


@pytest.mark.unit
@pytest.mark.requirement("DATA-11")
def test_the_interface_detail_schema_is_pinned_literally() -> None:
    """DATA-11's worked example. Declared field by field, so a change is visible in the diff."""
    assert TABLE_SCHEMAS["interface_details"].bare() == pa.schema(
        [
            pa.field("element_id", pa.string(), nullable=False),
            pa.field(
                "transport",
                pa.struct(
                    [
                        pa.field("protocol", pa.string(), nullable=False),
                        pa.field("interaction_mode", pa.string(), nullable=False),
                        pa.field("serialization", pa.string(), nullable=False),
                    ]
                ),
                nullable=False,
            ),
            pa.field("authentication_description", pa.string(), nullable=True),
            pa.field("request_schema_id", pa.string(), nullable=True),
            pa.field("response_schema_id", pa.string(), nullable=True),
            pa.field("delivery_semantics", pa.string(), nullable=False),
            pa.field("timeout_ms", pa.int64(), nullable=True),
            pa.field("idempotency_description", pa.string(), nullable=True),
            pa.field("content_hash", pa.string(), nullable=False),
        ]
    )


@pytest.mark.unit
@pytest.mark.requirement("DATA-12")
def test_the_baseline_type_vocabulary_is_exactly_five_types() -> None:
    assert BASELINE_TYPES == (
        pa.string(),
        pa.int64(),
        pa.bool_(),
        pa.timestamp("us", tz="UTC"),
        pa.date32(),
    )


@pytest.mark.unit
@pytest.mark.requirement("DATA-12")
def test_every_integer_is_int64() -> None:
    """One integer width across the whole set, so no W5 recipe needs a literal cast."""
    for table in ALL:
        for field in walk_fields(table.schema):
            if pa.types.is_integer(field.type):
                assert field.type == pa.int64(), f"{table.table_id}.{field.name}"


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_bare_drops_metadata_and_keeps_types_and_nullability() -> None:
    table = TABLE_SCHEMAS["elements"]
    bare = table.bare()
    assert bare.metadata is None
    assert all(field.metadata is None for field in bare)
    assert bare.names == table.schema.names
    assert [f.nullable for f in bare] == [f.nullable for f in table.schema]
    assert [f.type for f in bare] == [f.type for f in table.schema]


@pytest.mark.unit
@pytest.mark.requirement("DATA-10")
def test_the_storage_schema_version_is_a_version() -> None:
    """The DATA-56 migration anchor. A change to any schema above is a change to this."""
    assert STORAGE_SCHEMA_VERSION.count(".") == 2
