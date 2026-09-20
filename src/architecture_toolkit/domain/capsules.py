"""Structural types for foreign Arrow objects (DATA-34, DATA-43).

The Arrow C data interface is a set of dunder methods, not a class hierarchy. `pyarrow.Schema`,
`arro3.core.Schema`, a `polars.DataFrame` and anything else that speaks Arrow all export the same
capsules, and the only thing they have in common is those methods. A Protocol is therefore the
accurate type, and it is the one that lets `domain/protocols.py` describe the storage boundary
without importing pyarrow — which `rules/domain-layer-imports.yml` forbids and
`tests/unit/test_layering.py` re-checks.

**These are deliberately not in `protocols.py`.** That module declares the eight replaceable
subsystem seams `docs/contracts/core.md` names, and `tests/unit/test_protocols.py` asserts the set
stays exactly those eight. A capsule Protocol is not a seam: it is the shape of somebody else's
object, and mixing the two would make the registry meaningless.

`requested_schema` is part of the interface and is typed as `object` because it is a PyCapsule —
an opaque pointer with no Python type of its own. Every capsule return is `object` for the same
reason: the only honest thing to say about a `PyCapsule` is that it exists.
"""

from typing import Protocol, runtime_checkable

__all__ = [
    "ArrowArrayExportable",
    "ArrowSchemaExportable",
    "ArrowStreamExportable",
]


@runtime_checkable
class ArrowSchemaExportable(Protocol):
    """Anything that can hand over an Arrow schema: `pa.Schema`, `pa.Field`, arro3's `Schema`."""

    def __arrow_c_schema__(self) -> object: ...


@runtime_checkable
class ArrowArrayExportable(Protocol):
    """One contiguous batch or array: `pa.RecordBatch`, `pa.Array`, arro3's equivalents."""

    def __arrow_c_array__(self, requested_schema: object = None) -> tuple[object, object]: ...


@runtime_checkable
class ArrowStreamExportable(Protocol):
    """A sequence of batches. May be single-pass — see `storage.interchange.as_reader`.

    `pa.Table` satisfies this and can be consumed repeatedly; an arro3 `RecordBatchReader` from
    `DeltaTable.scan()` satisfies it and cannot. The Protocol cannot express the difference, so
    the storage layer treats every stream as single-pass and materializes when it needs two
    passes.
    """

    def __arrow_c_stream__(self, requested_schema: object = None) -> object: ...
