"""Normalizing foreign Arrow objects into pyarrow values (DATA-34, DATA-43).

The stack hands back three different libraries' objects for the same data.
`DeltaTable.schema().to_arrow()` returns an **arro3** `Schema`; `DeltaTable.scan()` and
DataFusion's `QueryBuilder().execute()` return arro3 `RecordBatchReader`s; DataFusion's
`DataFrame` exports a C stream. None of them is a `pyarrow` object and all of them speak the
Arrow C data interface, so this module is where that interface is spelled and everywhere else
works in pyarrow. `tests/unit/test_layering.py` asserts `arro3` appears in no `src` module and
`__arrow_c_` only here and in `domain/capsules.py`.

**Every stream is treated as single-pass.** A `pa.Table` can be read repeatedly and an arro3
reader from `scan()` cannot; the Protocol cannot tell them apart, so nothing here reads a stream
twice. A reader that has already been consumed raises `OSError: Cannot read from closed stream`
from inside arro3, which says nothing useful, so `as_reader` checks first and raises
`ConsumedStreamError` instead.

**`empty_reader` and `batches_for_registration` are not interchangeable and the difference is
load-bearing.** `SessionContext.register_record_batches(name, [[]])` *panics* — a pyo3
`PanicException`, not a Python error — so a table with no rows must be registered as one batch of
zero rows rather than as no batches. `from_arrow` over a genuinely empty reader is fine. The
matrix pins both.
"""

import pyarrow as pa

from architecture_toolkit.domain.capsules import ArrowSchemaExportable, ArrowStreamExportable
from architecture_toolkit.storage.errors import ConsumedStreamError

__all__ = [
    "as_reader",
    "as_schema",
    "as_table",
    "batches_for_registration",
    "empty_batch",
    "empty_reader",
    "tables_equal",
]


def as_schema(obj: object) -> pa.Schema:
    """Any Arrow schema exporter as a `pa.Schema`. Identity for one that already is."""
    if isinstance(obj, pa.Schema):
        return obj
    if not isinstance(obj, ArrowSchemaExportable):
        message = f"{type(obj).__name__} does not export an Arrow schema"
        raise TypeError(message)
    # Stub divergence 3 of 3: pyarrow 25's `schema()` accepts any object exporting the C
    # schema capsule — that is how an arro3 `Schema` is normalized — and the stub's overloads
    # cover only the iterable and mapping forms. Pinned by the stub qualification tests.
    return pa.schema(obj)  # pyrefly: ignore[bad-argument-type]


def empty_batch(schema: pa.Schema) -> pa.RecordBatch:
    """One batch of zero rows, typed by `schema`. See the module docstring for why it exists."""
    return pa.RecordBatch.from_arrays([pa.array([], type=f.type) for f in schema], schema=schema)


def batches_for_registration(table: pa.Table) -> list[pa.RecordBatch]:
    """The batches of `table`, never an empty list.

    A table with no rows has no batches, and handing DataFusion no batches panics the engine
    rather than raising. One zero-row batch carries the schema and registers cleanly.
    """
    batches = table.to_batches()
    return batches or [empty_batch(table.schema)]


def empty_reader(schema: pa.Schema) -> pa.RecordBatchReader:
    """A reader over no batches at all. Valid for `from_arrow`; **not** for
    `register_record_batches`."""
    return pa.RecordBatchReader.from_batches(schema, iter(()))


def as_reader(obj: object) -> pa.RecordBatchReader:
    """Any Arrow stream exporter as a `pa.RecordBatchReader`."""
    if isinstance(obj, pa.RecordBatchReader):
        return obj
    if getattr(obj, "closed", False):
        raise ConsumedStreamError(f"{type(obj).__name__} has already been consumed")
    if isinstance(obj, pa.Table):
        return pa.RecordBatchReader.from_batches(obj.schema, iter(batches_for_registration(obj)))
    if isinstance(obj, pa.RecordBatch):
        return pa.RecordBatchReader.from_batches(obj.schema, iter([obj]))
    if not isinstance(obj, ArrowStreamExportable):
        message = f"{type(obj).__name__} does not export an Arrow stream"
        raise TypeError(message)
    try:
        return pa.RecordBatchReader.from_stream(obj)
    except OSError as error:  # a consumed arro3 reader that did not advertise `closed`
        raise ConsumedStreamError(str(error)) from error


def as_table(obj: object) -> pa.Table:
    """Any Arrow stream exporter as a `pa.Table`. **Consumes** a single-pass reader."""
    if isinstance(obj, pa.Table):
        return obj
    if isinstance(obj, pa.RecordBatchReader):
        return obj.read_all()
    if getattr(obj, "closed", False):
        raise ConsumedStreamError(f"{type(obj).__name__} has already been consumed")
    return as_reader(obj).read_all()


def tables_equal(left: pa.Table, right: pa.Table, *, check_metadata: bool = False) -> bool:
    """`Table.equals` with the return type it actually has.

    `pyarrow-stubs` 20.0.0.20260819 declares `Table.equals` as returning a `Table`; pyarrow 25
    returns a `bool`. A wrong type type-checks, so callers go through here and the divergence is
    pinned in `tests/static/pyarrow_surface.py` and `tests/qualification/test_pyarrow_stub.py`.
    Drop this function when a corrected stub lands — those two tests will say when.

    Chunking is ignored by `Table.equals`, which is the behaviour the caller wants: two tables
    holding the same rows in different batches are equal.
    """
    return bool(left.equals(right, check_metadata=check_metadata))
