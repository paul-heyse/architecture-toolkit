"""The real interchange boundary: arro3 objects, C streams and DataFusion (DATA-34, DATA-43).

Everything here needs a library that is not pyarrow to hand back an Arrow object, which is the
whole point. `tests/unit/test_interchange.py` covers the pyarrow-only behaviour; these are the
ones that would pass vacuously without a Delta table and a DataFusion context.

Delta tables are written under `tmp_path` to *obtain* arro3 objects. This is not release
publication — W4 owns that — and nothing here asserts anything about manifests.
"""

from pathlib import Path

import pyarrow as pa
import pytest
from datafusion import SessionContext
from deltalake import DeltaTable, write_deltalake

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.storage.datafusion_adapter import register_snapshot
from architecture_toolkit.storage.digests import canonical_table, table_set_digests
from architecture_toolkit.storage.errors import ConsumedStreamError
from architecture_toolkit.storage.interchange import (
    as_reader,
    as_schema,
    as_table,
    batches_for_registration,
    empty_reader,
    tables_equal,
)
from architecture_toolkit.storage.mappings import assemble_model, compile_tables
from architecture_toolkit.storage.metadata import describe, field_roles, read_description, reattach
from architecture_toolkit.storage.schemas import TABLE_IDS, TABLE_SCHEMAS, TableRole
from architecture_toolkit.storage.snapshot import MaterializedPyArrowSnapshotProvider

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
ELEMENTS = TABLE_SCHEMAS["elements"]

ROWS: list[dict[str, object]] = [
    {
        "element_id": "elt-1",
        "model_id": "mod-1",
        "kind_id": "software.system",
        "name": "A system",
        "description": None,
        "lifecycle_state": "active",
        "aliases": ["The System"],
        "status": {
            "design_disposition": "accepted",
            "implementation_state": "implemented",
            "technical_qualification": "qualified",
            "client_acceptance": "accepted",
            "evidence_review": "observed",
        },
        "extensions": [{"namespace": "acme.finance", "key": "cost_centre", "value": "CC-42"}],
        "content_hash": "sha256:" + "1" * 64,
    },
    {
        "element_id": "elt-2",
        "model_id": "mod-1",
        "kind_id": "software.component",
        "name": "A component",
        "description": "with a description",
        "lifecycle_state": "retired",
        "aliases": [],
        "status": {
            "design_disposition": "candidate",
            "implementation_state": "not_implemented",
            "technical_qualification": "not_qualified",
            "client_acceptance": "not_requested",
            "evidence_review": "unreviewed",
        },
        "extensions": [],
        "content_hash": "sha256:" + "2" * 64,
    },
]


def written(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    location = tmp_path / "elements"
    table = pa.Table.from_pylist(rows, schema=ELEMENTS.schema)
    write_deltalake(location, table)
    return location


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-43")
def test_a_delta_schema_comes_back_as_arro3_and_normalizes_to_the_declared_schema(
    tmp_path: Path,
) -> None:
    """`DeltaTable.schema().to_arrow()` is an arro3 `Schema`, not a pyarrow one."""
    location = written(tmp_path, ROWS)
    exported = DeltaTable(location, version=0).schema().to_arrow()
    assert not isinstance(exported, pa.Schema), (
        "upstream changed: this is the reason as_schema exists"
    )
    normalized = as_schema(exported)
    assert isinstance(normalized, pa.Schema)
    assert normalized.equals(ELEMENTS.bare(), check_metadata=False)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-44")
def test_delta_keeps_field_metadata_and_drops_schema_metadata(tmp_path: Path) -> None:
    """The asymmetry `metadata.reattach` exists for. Pinned so a deltalake change is noticed."""
    location = tmp_path / "described"
    described = describe(ELEMENTS.schema, table_id="elements", role=TableRole.ENTITY)
    write_deltalake(location, pa.Table.from_pylist(ROWS, schema=described))

    read = DeltaTable(location, version=0).to_pyarrow_table()
    assert read_description(read.schema).table_id is None, "schema-level metadata survived"
    assert field_roles(read.schema)["element_id"] == "identity", "field metadata was dropped"

    restored = reattach(read, ELEMENTS)
    assert read_description(restored.schema).table_id == "elements"
    assert restored.schema.equals(described, check_metadata=True)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-43")
def test_a_scan_reader_normalizes_and_is_single_pass(tmp_path: Path) -> None:
    location = written(tmp_path, ROWS)
    delta = DeltaTable(location, version=0)
    reader = delta.scan()
    assert not isinstance(reader, pa.RecordBatchReader)

    materialized = as_table(reader)
    assert materialized.num_rows == len(ROWS)
    assert tables_equal(materialized.cast(ELEMENTS.bare()), delta.to_pyarrow_table())

    # Reading the same arro3 reader again is the failure `ConsumedStreamError` names.
    with pytest.raises(ConsumedStreamError):
        as_table(reader)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-10", "DATA-12")
def test_delta_preserves_nested_nullability_lists_and_structs(tmp_path: Path) -> None:
    """The declared schema survives a round trip unchanged except for schema-level metadata."""
    location = written(tmp_path, ROWS)
    read = DeltaTable(location, version=0).to_pyarrow_table()
    assert read.schema.equals(ELEMENTS.bare(), check_metadata=False)
    assert read.to_pylist() == ROWS
    # List item fields come back named `element`, which is why the schema declares that name.
    aliases = read.schema.field("aliases")
    assert aliases.type.field(0).name == "element"


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-10")
def test_an_empty_typed_table_keeps_its_schema_through_delta(tmp_path: Path) -> None:
    """§11B: typed empties. A table with no rows is not a table with no schema."""
    location = written(tmp_path, [])
    read = DeltaTable(location, version=0).to_pyarrow_table()
    assert read.num_rows == 0
    assert read.schema.equals(ELEMENTS.bare(), check_metadata=False)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-34")
def test_register_record_batches_panics_on_an_empty_batch_list() -> None:
    """Why `batches_for_registration` synthesizes a zero-row batch rather than passing `[]`.

    A pyo3 `PanicException` is not an `Exception` subclass in the usual sense and is not
    something a caller can reasonably be expected to handle, so the shape is avoided entirely.
    """
    context = SessionContext()
    # Narrowed to the pyo3 panic type by name: importing `pyo3_runtime` to name it directly would
    # take a dependency on an implementation detail of the datafusion wheel.
    with pytest.raises(BaseException) as caught:  # noqa: PT011
        context.register_record_batches("empty", [[]])
    assert type(caught.value).__name__ == "PanicException"


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-34")
def test_the_synthesized_empty_batch_registers_and_queries_as_zero_rows() -> None:
    context = SessionContext()
    empty = ELEMENTS.bare().empty_table()
    context.register_record_batches("elements", [batches_for_registration(empty)])
    result = context.sql("SELECT count(*) AS n FROM elements").to_arrow_table()
    assert result.to_pylist() == [{"n": 0}]


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-34", "DATA-43")
def test_a_table_and_a_reader_reach_datafusion_identically_through_the_c_stream() -> None:
    """`from_arrow` accepts either; the results must not depend on which one a provider hands it."""
    table = pa.Table.from_pylist(ROWS, schema=ELEMENTS.bare())
    query = "SELECT element_id FROM elements ORDER BY element_id"

    from_table = SessionContext()
    from_table.from_arrow(table, name="elements")

    from_reader = SessionContext()
    from_reader.from_arrow(as_reader(table), name="elements")

    assert (
        from_table.sql(query).to_arrow_table().to_pylist()
        == from_reader.sql(query).to_arrow_table().to_pylist()
        == [{"element_id": "elt-1"}, {"element_id": "elt-2"}]
    )


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-34")
def test_an_empty_reader_is_valid_for_from_arrow_even_though_it_has_no_batches() -> None:
    """The half of the pair `register_record_batches` cannot do."""
    context = SessionContext()
    context.from_arrow(empty_reader(ELEMENTS.bare()), name="elements")
    result = context.sql("SELECT count(*) AS n FROM elements").to_arrow_table()
    assert result.to_pylist() == [{"n": 0}]
    assert context.table("elements").schema().names == ELEMENTS.bare().names


# -- the materialized provider --------------------------------------------------------------------


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-34", "DATA-51")
def test_the_provider_reads_exactly_the_version_it_is_given(tmp_path: Path) -> None:
    """Two versions of one table, and no way to ask for "the latest"."""
    location = tmp_path / "elements"
    write_deltalake(location, pa.Table.from_pylist(ROWS, schema=ELEMENTS.schema))
    write_deltalake(location, pa.Table.from_pylist([], schema=ELEMENTS.schema), mode="overwrite")
    provider = MaterializedPyArrowSnapshotProvider({"elements": location})
    assert provider.read("elements", version=0).num_rows == len(ROWS)
    assert provider.read("elements", version=1).num_rows == 0


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-34")
def test_the_provider_reports_the_schema_storage_actually_holds(tmp_path: Path) -> None:
    location = written(tmp_path, ROWS)
    provider = MaterializedPyArrowSnapshotProvider({"elements": location})
    schema = provider.schema_for("elements", version=0)
    assert schema.equals(ELEMENTS.bare(), check_metadata=False)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-34")
def test_open_yields_one_zero_row_batch_for_an_empty_table(tmp_path: Path) -> None:
    """§11B's typed empties, and the reason `open` does not return `empty_reader`.

    A reader over no batches is fine for `from_arrow` and fatal for `register_record_batches`,
    which is what this provider exists to feed.
    """
    location = written(tmp_path, [])
    provider = MaterializedPyArrowSnapshotProvider({"elements": location})
    reader = provider.open("elements", version=0)
    batches = list(reader)
    assert len(batches) == 1
    assert batches[0].num_rows == 0
    assert batches[0].schema.equals(ELEMENTS.bare(), check_metadata=False)


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-34")
def test_register_reproduces_the_qualified_adapter_exactly(tmp_path: Path) -> None:
    """`register_snapshot` now delegates here, so the two must not be able to disagree."""
    location = written(tmp_path, ROWS)
    query = "SELECT element_id FROM elements ORDER BY element_id"

    through_adapter = SessionContext()
    adapter_schema = register_snapshot(through_adapter, "elements", location, version=0)

    through_provider = SessionContext()
    provider = MaterializedPyArrowSnapshotProvider({"elements": location})
    provider_schema = provider.register(through_provider, "elements", "elements", version=0)

    assert adapter_schema.equals(provider_schema)
    assert (
        through_adapter.sql(query).to_arrow_table().to_pylist()
        == through_provider.sql(query).to_arrow_table().to_pylist()
    )


@pytest.mark.qualification
@pytest.mark.interop
@pytest.mark.requirement("DATA-10", "DATA-14", "DATA-45")
def test_a_compiled_table_set_survives_delta_and_keeps_its_digests(tmp_path: Path) -> None:
    """The end-to-end claim: model to Arrow to Delta and back, same digests and same model.

    Row order is not guaranteed across a storage boundary, so the assertion on the model is
    `model_digest` equality rather than record equality — which is exactly the distinction the
    canonical hash exists to make.
    """
    model = parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))
    table_set = compile_tables(model)
    before = table_set_digests(table_set)

    read_back: dict[str, pa.Table] = {}
    for table_id in TABLE_IDS:
        location = tmp_path / table_id
        write_deltalake(location, table_set[table_id])
        read_back[table_id] = reattach(
            DeltaTable(location, version=0).to_pyarrow_table(), TABLE_SCHEMAS[table_id]
        )

    restored = table_set.with_tables(read_back)
    assert table_set_digests(restored) == before
    assert model_digest(assemble_model(restored)) == model_digest(model)
    for table_id in TABLE_IDS:
        assert canonical_table(table_id, restored[table_id]).equals(
            canonical_table(table_id, table_set[table_id])
        )
