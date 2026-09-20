"""Materialized, explicitly version-pinned baseline; native FFI is deliberately disabled.

The implementation moved to `storage/snapshot.py` at W3, where it became a
`SnapshotProvider`. This function keeps its signature, its behaviour and its callers: it is what
`tests/qualification/test_data_stack.py` qualified, and a qualified entry point is not renamed
because a better-factored one now exists behind it.
"""

from pathlib import Path

import pyarrow as pa
from datafusion import SessionContext

from architecture_toolkit.storage.snapshot import MaterializedPyArrowSnapshotProvider


def register_snapshot(
    context: SessionContext, name: str, location: str | Path, *, version: int
) -> pa.Schema:
    """Register an immutable selection, retaining schema even for an empty table.

    All rows are materialized in memory. This is appropriate for small architecture
    models, not an unbounded analytics source. Callers must choose the version from
    a release manifest; there is intentionally no latest-version default.
    """
    provider = MaterializedPyArrowSnapshotProvider({name: location})
    return provider.register(context, name, name, version=version)
