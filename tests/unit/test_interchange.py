"""Normalizing foreign Arrow objects (DATA-34, DATA-43).

The arro3 and DataFusion halves need a real Delta table and live in
`tests/qualification/test_arrow_interchange.py`. These are the pyarrow-only behaviours, including
the two that exist because of how the rest of the stack behaves: the synthesized empty batch and
the refusal to read a consumed stream twice.
"""

import pyarrow as pa
import pytest

from architecture_toolkit.storage.errors import ConsumedStreamError
from architecture_toolkit.storage.interchange import (
    as_reader,
    as_schema,
    as_table,
    batches_for_registration,
    empty_batch,
    empty_reader,
    tables_equal,
)

SCHEMA = pa.schema(
    [pa.field("x", pa.string(), nullable=False), pa.field("n", pa.int64(), nullable=True)]
)
ROWS = [{"x": "a", "n": 1}, {"x": "b", "n": None}, {"x": "c", "n": 3}]


def table() -> pa.Table:
    return pa.Table.from_pylist(ROWS, schema=SCHEMA)


class _SchemaExporter:
    def __arrow_c_schema__(self) -> object:
        return SCHEMA.__arrow_c_schema__()


class _StreamExporter:
    def __arrow_c_stream__(self, requested_schema: object = None) -> object:
        del requested_schema
        return table().__arrow_c_stream__()


@pytest.mark.unit
@pytest.mark.requirement("DATA-43")
def test_as_schema_is_identity_for_a_pyarrow_schema() -> None:
    assert as_schema(SCHEMA) is SCHEMA


@pytest.mark.unit
@pytest.mark.requirement("DATA-43")
def test_as_schema_normalizes_any_capsule_exporter() -> None:
    assert as_schema(_SchemaExporter()).equals(SCHEMA)


@pytest.mark.unit
@pytest.mark.requirement("DATA-43")
def test_a_non_arrow_object_is_a_type_error_not_a_capsule_crash() -> None:
    with pytest.raises(TypeError, match="does not export an Arrow schema"):
        as_schema(object())
    with pytest.raises(TypeError, match="does not export an Arrow stream"):
        as_reader(object())


@pytest.mark.unit
@pytest.mark.requirement("DATA-43")
def test_as_reader_accepts_a_table_a_batch_a_reader_and_an_exporter() -> None:
    source = table()
    assert as_reader(source).read_all().equals(source)
    assert as_reader(source.to_batches()[0]).read_all().num_rows == source.num_rows
    reader = pa.RecordBatchReader.from_batches(SCHEMA, iter(source.to_batches()))
    assert as_reader(reader) is reader
    assert as_reader(_StreamExporter()).read_all().equals(source)


@pytest.mark.unit
@pytest.mark.requirement("DATA-43")
def test_as_table_materializes_every_shape() -> None:
    source = table()
    assert as_table(source) is source
    assert as_table(_StreamExporter()).equals(source)
    reader = pa.RecordBatchReader.from_batches(SCHEMA, iter(source.to_batches()))
    assert as_table(reader).equals(source)


@pytest.mark.unit
@pytest.mark.requirement("DATA-34", "DATA-43")
def test_a_consumed_pyarrow_reader_reads_as_empty_rather_than_raising() -> None:
    """Measured, and the reason nothing here reads a stream twice.

    A pyarrow reader over an exhausted iterator does not complain: it yields a zero-row table
    with the right schema, which is the worst possible failure because it looks like a table that
    legitimately has no rows. An arro3 reader from `DeltaTable.scan()` raises instead, and
    `as_reader` turns that into `ConsumedStreamError` —
    `tests/qualification/test_arrow_interchange.py` pins that half, where a Delta table exists.
    """
    reader = pa.RecordBatchReader.from_batches(SCHEMA, iter(table().to_batches()))
    assert reader.read_all().num_rows == len(ROWS)
    second = as_table(reader)
    assert second.num_rows == 0
    assert second.schema.equals(SCHEMA)


@pytest.mark.unit
@pytest.mark.requirement("DATA-34", "DATA-43")
def test_an_object_that_advertises_it_is_closed_is_refused_before_the_capsule() -> None:
    """`as_reader` checks `closed` first, so the caller gets a named error, not an arro3 OSError."""

    class Closed:
        closed = True

        def __arrow_c_stream__(self, requested_schema: object = None) -> object:
            raise AssertionError("must not be reached")

    with pytest.raises(ConsumedStreamError, match="already been consumed"):
        as_reader(Closed())
    with pytest.raises(ConsumedStreamError, match="already been consumed"):
        as_table(Closed())


@pytest.mark.unit
@pytest.mark.requirement("DATA-34")
def test_an_empty_table_registers_as_one_zero_row_batch_never_as_none() -> None:
    """`SessionContext.register_record_batches(name, [[]])` panics rather than raising.

    So the synthesis is load-bearing, not a tidiness measure. The panic itself is pinned in
    `tests/qualification/test_arrow_interchange.py`, where a real DataFusion context exists.
    """
    empty = SCHEMA.empty_table()
    assert empty.to_batches() == []
    batches = batches_for_registration(empty)
    assert len(batches) == 1
    assert batches[0].num_rows == 0
    assert batches[0].schema.equals(SCHEMA)


@pytest.mark.unit
@pytest.mark.requirement("DATA-34")
def test_batches_for_registration_passes_a_non_empty_table_through() -> None:
    source = table()
    assert [b.num_rows for b in batches_for_registration(source)] == [
        b.num_rows for b in source.to_batches()
    ]


@pytest.mark.unit
@pytest.mark.requirement("DATA-34")
def test_an_empty_reader_has_no_batches_but_keeps_its_schema() -> None:
    """The other half of the pair: valid for `from_arrow`, invalid for `register_record_batches`."""
    reader = empty_reader(SCHEMA)
    assert reader.schema.equals(SCHEMA)
    read = reader.read_all()
    assert read.num_rows == 0
    assert read.schema.equals(SCHEMA)
    assert empty_batch(SCHEMA).num_rows == 0


@pytest.mark.unit
@pytest.mark.requirement("DATA-45")
def test_tables_equal_returns_a_bool_and_ignores_chunking() -> None:
    """The stub declares `Table.equals` as returning a `Table`; this is the corrected surface."""
    source = table()
    rechunked = pa.Table.from_batches(
        [source.slice(0, 1).to_batches()[0], source.slice(1).combine_chunks().to_batches()[0]],
        schema=SCHEMA,
    )
    assert tables_equal(source, rechunked) is True
    assert tables_equal(source, SCHEMA.empty_table()) is False
