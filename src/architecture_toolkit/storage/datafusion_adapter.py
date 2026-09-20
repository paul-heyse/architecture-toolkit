"""Materialized, explicitly version-pinned baseline; native FFI is deliberately disabled."""

from pathlib import Path

import pyarrow as pa
from datafusion import SessionContext
from deltalake import DeltaTable


def register_snapshot(
    context: SessionContext, name: str, location: str | Path, *, version: int
) -> pa.Schema:
    """Register an immutable selection, retaining schema even for an empty table.

    All rows are materialized in memory. This is appropriate for small architecture
    models, not an unbounded analytics source. Callers must choose the version from
    a release manifest; there is intentionally no latest-version default.
    """
    if type(version) is not int or version < 0:
        raise ValueError("an explicit nonnegative table version is required")
    table = DeltaTable(location, version=version).to_pyarrow_table()
    batches = table.to_batches()
    if not batches:
        batches = [
            pa.RecordBatch.from_arrays(
                [pa.array([], type=field.type) for field in table.schema], schema=table.schema
            )
        ]
    context.register_record_batches(name, [batches])
    return table.schema
