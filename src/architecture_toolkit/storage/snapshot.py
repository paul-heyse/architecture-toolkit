"""The materialized PyArrow snapshot provider (DATA-34, DATA-51, §11B).

This is the *qualified fallback*, not a placeholder. `docs/toolchain.md` records that direct
native FFI is incompatible under the current lock, and `docs/contracts/data.md` requires that no
Dataset, stream or native candidate replace this one without exact-stack qualification. So it
reads a Delta table at an explicitly named version, materializes it, and hands DataFusion batches.
All rows are in memory, which is appropriate for an architecture model and would not be for an
unbounded analytics source; `describe()` says so rather than leaving a caller to find out.

**There is no latest-version default and there never will be.** Global invariant 5 — published
releases never resolve an implicit latest table version — is enforced three ways here: `version`
is keyword-only with no default, `require_version` rejects anything that is not a nonnegative
`int` (including `True`, which Python would otherwise accept as `1`), and
`rules/no-implicit-latest-delta-version.yml` rejects a `DeltaTable(...)` call with no `version=`
anywhere in the source tree.

`open()` deliberately yields the **synthesized** empty batch rather than an empty reader. This
provider exists to feed `SessionContext.register_record_batches`, which panics on an empty batch
list; `storage/interchange.py` explains the pair.
"""

from collections.abc import Mapping
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Final

import pyarrow as pa
from datafusion import SessionContext
from deltalake import DeltaTable

from architecture_toolkit.domain.providers import Materialization, SnapshotProviderDescription
from architecture_toolkit.storage.errors import UnknownTableError
from architecture_toolkit.storage.interchange import batches_for_registration

__all__ = ["LIBRARIES", "MaterializedPyArrowSnapshotProvider", "require_version"]

LIBRARIES: Final[tuple[str, ...]] = ("pyarrow", "deltalake", "datafusion", "arro3-core")
"""The four distributions whose behaviour this provider's correctness depends on."""


def require_version(version: int) -> int:
    """An explicit, nonnegative table version, or `ValueError`.

    `type(version) is not int` rather than `isinstance`, because `bool` is a subclass of `int`
    and `DeltaTable(location, version=True)` would silently read version 1.
    """
    if type(version) is not int or version < 0:
        raise ValueError("an explicit nonnegative table version is required")
    return version


class MaterializedPyArrowSnapshotProvider:
    """Reads named Delta tables at explicit versions and materializes them to PyArrow.

    `locations` maps a table id to where that table lives. W4 builds the mapping from a release
    manifest; nothing here resolves a location by convention, because a provider that can guess a
    path can guess a wrong one.
    """

    def __init__(self, locations: Mapping[str, Path | str]) -> None:
        self._locations: Mapping[str, Path | str] = dict(locations)

    def describe(self) -> SnapshotProviderDescription:
        """Deterministic: no paths, no timestamps. Two runs on one lock compare equal."""
        return SnapshotProviderDescription(
            provider_type=type(self).__name__,
            materialization=Materialization.MATERIALIZED,
            preserves_typed_empties=True,
            library_versions=tuple(
                (name, distribution_version(name)) for name in sorted(LIBRARIES)
            ),
            native_ffi_enabled=False,
        )

    def _location(self, table_id: str) -> Path | str:
        try:
            return self._locations[table_id]
        except KeyError:
            raise UnknownTableError(table_id) from None

    def read(self, table_id: str, *, version: int) -> pa.Table:
        """The whole table at exactly `version`."""
        location = self._location(table_id)
        return DeltaTable(location, version=require_version(version)).to_pyarrow_table()

    def schema_for(self, table_id: str, *, version: int) -> pa.Schema:
        """What storage actually holds, read from the materialized table.

        Materializing to read a schema is wasteful and is accepted here: this provider is the
        permanent fallback and its correctness matters more than its cost. W4's Dataset and
        stream providers read `DeltaTable.schema().to_arrow()` through `interchange.as_schema`
        instead, which is one of the things that qualification has to compare.
        """
        return self.read(table_id, version=version).schema

    def open(self, table_id: str, *, version: int) -> pa.RecordBatchReader:
        """A reader over the table's batches, with an empty table giving one zero-row batch."""
        table = self.read(table_id, version=version)
        return pa.RecordBatchReader.from_batches(
            table.schema, iter(batches_for_registration(table))
        )

    def register(
        self, context: SessionContext, name: str, table_id: str, *, version: int
    ) -> pa.Schema:
        """Register one snapshot in a DataFusion context and return the schema registered."""
        table = self.read(table_id, version=version)
        context.register_record_batches(name, [batches_for_registration(table)])
        return table.schema
