"""The pyarrow surface `storage/` uses, checked against `pyarrow-stubs` (CORE-53, CORE-58).

`pyarrow` ships no `py.typed`, so every annotation reaching it would be `Any` and every function
mentioning a pyarrow type would count as `[coverage-partial]` under
`pyrefly coverage check --strict`. `pyarrow-stubs` closes that, but its declared target is
pyarrow major 20 while the lock pins 25, so the stub could be *wrong* rather than merely absent —
a worse failure, because a wrong return type type-checks and then breaks at run time.

This file is the qualification. Every call `storage/` makes is written once with the return type
it must have, and `assert_type` is the assertion: a stub that misreports the 25.x surface fails
`pyrefly check` here rather than somewhere downstream. `tests/qualification/test_pyarrow_stub.py`
runs the same expressions so a stub that is merely *stale* — declaring something the runtime no
longer has — fails too. Static and runtime together are what make the stub trustworthy; neither
alone is.
"""

from __future__ import annotations

from typing import Any, assert_type

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.ipc as ipc

# --- schema, field and type construction ------------------------------------------------------
_string: pa.DataType = pa.string()
_int64: pa.DataType = pa.int64()
_bool: pa.DataType = pa.bool_()
_timestamp: pa.DataType = pa.timestamp("us", tz="UTC")
_date: pa.DataType = pa.date32()
_item: pa.Field = pa.field("element", pa.string(), nullable=False)
_list: pa.DataType = pa.list_(_item)
_struct: pa.DataType = pa.struct([pa.field("a", pa.string(), nullable=False)])
_map: pa.DataType = pa.map_(pa.string(), pa.string())
_dictionary: pa.DataType = pa.dictionary(pa.int32(), pa.string())

_field: pa.Field = pa.field("x", _string, nullable=True, metadata={b"k": b"v"})
_schema: pa.Schema = pa.schema([_field])

assert_type(_schema.names, list[str])
assert_type(_schema.field("x"), pa.Field)
assert_type(_schema.empty_table(), pa.Table)
assert_type(_schema.equals(_schema), bool)
_schema_metadata: dict[bytes, bytes] | None = _schema.metadata
_with_metadata: pa.Schema = _schema.with_metadata({b"k": b"v"})
_remove_metadata: pa.Schema = _schema.remove_metadata()
_field_with_metadata: pa.Field = _field.with_metadata({b"role": b"identity"})
_field_metadata: dict[bytes, bytes] | None = _field.metadata

# --- tables and batches ------------------------------------------------------------------------
_table: pa.Table = pa.Table.from_pylist([{"x": "a"}], schema=_schema)
assert_type(_table.num_rows, int)
assert_type(_table.schema, pa.Schema)
assert_type(_table.to_pylist(), list[dict[str, Any]])
# **Stub defect 1 of 2.** `pyarrow-stubs` 20.0.0.20260819 declares `Table.equals` as returning a
# `Table`; pyarrow 25.0.1 returns `bool`. Asserted here as *declared*, not as true, so a corrected
# stub fails this line and `storage.interchange.tables_equal` can be dropped along with it.
# `tests/qualification/test_pyarrow_stub.py` pins the runtime truth on the other side.
assert_type(_table.equals(_table), pa.Table)
_cast: pa.Table = _table.cast(_schema)
_combined: pa.Table = _table.combine_chunks()
_sorted: pa.Table = _table.sort_by([("x", "ascending")])
_replaced: pa.Table = _table.replace_schema_metadata({b"k": b"v"})
_batches: list[pa.RecordBatch] = _table.to_batches()
_from_batches: pa.Table = pa.Table.from_batches(_batches, schema=_schema)
_from_arrays: pa.Table = pa.Table.from_arrays([pa.array(["a"], type=pa.string())], schema=_schema)
_batch: pa.RecordBatch = pa.RecordBatch.from_pylist([{"x": "a"}], schema=_schema)
assert_type(_batch.num_rows, int)
_batch_schema: pa.Schema = _batch.schema
_struct_array: pa.StructArray = pa.StructArray.from_arrays(
    [pa.array(["a"], type=pa.string())], fields=[pa.field("a", pa.string(), nullable=False)]
)

# --- readers and the C stream --------------------------------------------------------------
_reader: pa.RecordBatchReader = pa.RecordBatchReader.from_batches(_schema, iter(_batches))
_reader_schema: pa.Schema = _reader.schema
_read_all: pa.Table = _reader.read_all()
_from_stream: pa.RecordBatchReader = pa.RecordBatchReader.from_stream(_table)
_table_from_object: pa.Table = pa.table(_table)
# **Stub defect 3 of 3.** pyarrow 25's `schema()` accepts any capsule exporter; the stub's
# overloads cover only the iterable and mapping forms. `storage.interchange.as_schema` carries
# the suppression, narrowed by an `isinstance` check against the capsule Protocol.
_schema_from_object: pa.Schema = pa.schema(_schema)

# The PyCapsule dunders `storage/interchange.py` normalizes foreign objects through.
_capsule_schema: object = _schema.__arrow_c_schema__()
_capsule_stream: object = _table.__arrow_c_stream__()
_capsule_array: tuple[object, object] = _batch.__arrow_c_array__()

# --- compute, dataset and IPC -----------------------------------------------------------------
_encoded: pa.ChunkedArray = pc.dictionary_encode(_table.column("x"))
# **Stub defect 2 of 2.** `dictionary_decode` is absent from the stub and present in pyarrow
# 25.0.1. Narrow suppression rather than a project-wide fallback, paired with the runtime test.
_decoded: pa.ChunkedArray = pc.dictionary_decode(_encoded)  # pyrefly: ignore[missing-attribute]
_dataset: ds.Dataset = ds.dataset([_table])
_dataset_schema: pa.Schema = _dataset.schema
_sink: pa.BufferOutputStream = pa.BufferOutputStream()
with ipc.new_stream(_sink, _schema) as _writer:
    _writer.write_table(_table)
_ipc_bytes: pa.Buffer = _sink.getvalue()
