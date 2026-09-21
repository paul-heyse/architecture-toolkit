"""The SnapshotProvider ladder (DATA-34, DATA-51, DATA-52, §11B).

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

**Four rungs, one default.** DATA-52 says "qualify PyArrow Dataset and Delta scan/Arrow-stream
providers *before* replacing the materialized provider", and qualifying is not replacing. All
three candidates pass the full matrix and all three are selectable by name; the materialized one
stays the default, because `data.md` calls it the "permanent simple fallback; current qualified
baseline" and changing a qualified default is a measured decision rather than a side effect of
the wave that first tested the alternatives.

The fourth rung, the native Delta/DataFusion FFI provider, is written as a class that **always
refuses**. deltalake 1.6.4 exports a DataFusion 55.x table provider and the lock pins DataFusion
54, and the library itself rejects the mismatch — so the refusal is upstream and this only names
it. It exists as a class rather than as a paragraph because `docs/agent-handoff.md` says "Never
enable native Delta/DataFusion FFI merely because import/registration exists", and a rule written
as code is one somebody has to delete deliberately.
"""

from collections.abc import Mapping
from importlib.metadata import version as distribution_version
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pyarrow as pa
from datafusion import SessionContext

from architecture_toolkit.domain.providers import Materialization, SnapshotProviderDescription
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.errors import StorageError, UnknownTableError
from architecture_toolkit.storage.interchange import as_reader, batches_for_registration
from architecture_toolkit.storage.schemas import schema_for

__all__ = [
    "DEFAULT_PROVIDER",
    "LIBRARIES",
    "PROVIDERS",
    "ArrowStreamSnapshotProvider",
    "MaterializedPyArrowSnapshotProvider",
    "NativeDeltaDataFusionSnapshotProvider",
    "NativeProviderUnavailableError",
    "PyArrowDatasetSnapshotProvider",
    "provider_named",
    "replace_description",
    "require_version",
]

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
        return delta.read_version(location, version=require_version(version))

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


class PyArrowDatasetSnapshotProvider(MaterializedPyArrowSnapshotProvider):
    """The preferred candidate: a lazy dataset over one pinned version (DATA-52).

    `to_pyarrow_dataset()` defers reading until a scan asks for rows, which lets DataFusion push
    projection and filtering down. **Laziness does not relax the pin** — a dataset built from
    version 0 still reads version 0 after the table has moved on, which the qualification tests
    assert rather than assume, because a lazy provider that silently followed the tip would break
    invariant 5 in the least visible way possible.

    Inherits `read` so a caller that genuinely wants the whole table in memory still gets the
    materialized path; what changes is how DataFusion sees it.
    """

    def describe(self) -> SnapshotProviderDescription:
        return replace_description(
            super().describe(), provider_type=type(self).__name__, how=Materialization.LAZY_DATASET
        )

    def dataset(self, table_id: str, *, version: int) -> pa.dataset.Dataset:
        return delta.open_dataset(self._location(table_id), version=require_version(version))

    def schema_for(self, table_id: str, *, version: int) -> pa.Schema:
        """Read from the dataset rather than by materializing, which is the point of this rung."""
        return self.dataset(table_id, version=version).schema

    def open(self, table_id: str, *, version: int) -> pa.RecordBatchReader:
        return self.dataset(table_id, version=version).scanner().to_reader()

    def register(
        self, context: SessionContext, name: str, table_id: str, *, version: int
    ) -> pa.Schema:
        dataset = self.dataset(table_id, version=version)
        context.register_dataset(name, dataset)
        return dataset.schema


class ArrowStreamSnapshotProvider(MaterializedPyArrowSnapshotProvider):
    """The streaming candidate: `DeltaTable.scan()` through the Arrow C stream (DATA-43).

    `scan()` returns an **arro3** reader, not a pyarrow one, which is the boundary
    `storage/interchange.py` exists to normalize. The reader is single-pass, so `schema_for` opens
    its own rather than consuming the one a caller is about to read — a provider whose
    `schema_for` quietly emptied its `open` would be the worst kind of correct.

    **A measured divergence, normalized here.** Under deltalake 1.6.4, `scan()` returns string
    columns as `string_view` where `to_pyarrow_table()` and `to_pyarrow_dataset()` return
    `string`. The values are identical and the cast is lossless, but §11B requires a provider to
    "expose the expected Arrow schema for that table version", and `string_view` is not it — so
    every batch is cast to the declared schema on the way out. The cast is lazy, one batch at a
    time, so the streaming property survives it.

    The divergence itself is pinned in `tests/qualification/test_arrow_matrix.py` rather than
    silently absorbed: a deltalake release that stops returning `string_view` should be noticed,
    not discovered later by someone wondering why the cast exists.
    """

    def describe(self) -> SnapshotProviderDescription:
        return replace_description(
            super().describe(), provider_type=type(self).__name__, how=Materialization.STREAMING
        )

    def schema_for(self, table_id: str, *, version: int) -> pa.Schema:
        del version
        return schema_for(table_id).bare()

    def open(self, table_id: str, *, version: int) -> pa.RecordBatchReader:
        declared = schema_for(table_id).bare()
        raw = as_reader(
            delta.open_reader(self._location(table_id), version=require_version(version))
        )
        return pa.RecordBatchReader.from_batches(declared, (batch.cast(declared) for batch in raw))

    def register(
        self, context: SessionContext, name: str, table_id: str, *, version: int
    ) -> pa.Schema:
        reader = self.open(table_id, version=version)
        schema = reader.schema
        context.from_arrow(reader, name=name)
        return schema


class NativeProviderUnavailableError(StorageError):
    """The native Delta/DataFusion FFI provider cannot be used under this lock.

    Its own type so a caller can tell "this optimization is unavailable" from "this read failed",
    which are different operational facts even though both stop the same call.
    """


class NativeDeltaDataFusionSnapshotProvider(MaterializedPyArrowSnapshotProvider):
    """The optional optimization, disabled — and disabled in code rather than in prose (DATA-52).

    deltalake 1.6.4 exports a DataFusion 55.x FFI table provider and the lock pins DataFusion 54.
    The library rejects the mismatch itself, with a message that says segfaults are the
    alternative, so nothing here is working around a limitation: this names it, refuses early, and
    gives the refusal a type.

    Enabling it needs aligned FFI majors *and* both-platform qualification, in that order.
    `describe().native_ffi_enabled` stays `False`, which is the claim a qualification artifact
    records.
    """

    def describe(self) -> SnapshotProviderDescription:
        return replace_description(
            super().describe(), provider_type=type(self).__name__, how=Materialization.STREAMING
        )

    def _refuse(self) -> NativeProviderUnavailableError:
        return NativeProviderUnavailableError(
            "the native Delta/DataFusion provider is disabled: deltalake "
            f"{distribution_version('deltalake')} exports a DataFusion 55.x FFI provider and this "
            f"lock pins datafusion {distribution_version('datafusion')}. Aligning the majors and "
            "qualifying on both platforms is what enables it; importing it is not."
        )

    def schema_for(self, table_id: str, *, version: int) -> pa.Schema:
        del table_id, version
        raise self._refuse()

    def open(self, table_id: str, *, version: int) -> pa.RecordBatchReader:
        del table_id, version
        raise self._refuse()

    def register(
        self, context: SessionContext, name: str, table_id: str, *, version: int
    ) -> pa.Schema:
        del context, name, table_id, version
        raise self._refuse()


def replace_description(
    description: SnapshotProviderDescription, *, provider_type: str, how: Materialization
) -> SnapshotProviderDescription:
    """Re-derive a description for a subclass through validation, never `model_copy(update=)`."""
    return description.model_validate(
        dict(description) | {"provider_type": provider_type, "materialization": how}
    )


PROVIDERS: Final[Mapping[str, type[MaterializedPyArrowSnapshotProvider]]] = MappingProxyType(
    {
        "materialized": MaterializedPyArrowSnapshotProvider,
        "dataset": PyArrowDatasetSnapshotProvider,
        "stream": ArrowStreamSnapshotProvider,
        "native": NativeDeltaDataFusionSnapshotProvider,
    }
)
"""Every provider, by the name a caller selects it with. `native` is listed and unusable, which is
more honest than omitting it: a reader asking "can I use the FFI provider" gets an answer."""

DEFAULT_PROVIDER: Final[str] = "materialized"
"""DATA-52: qualifying the candidates is not replacing the baseline."""


def provider_named(
    name: str, locations: Mapping[str, Path | str]
) -> MaterializedPyArrowSnapshotProvider:
    """Build a provider by name, or `UnknownTableError`-style refusal for an unknown one."""
    try:
        factory = PROVIDERS[name]
    except KeyError:
        message = f"unknown snapshot provider {name!r}; choose one of {sorted(PROVIDERS)}"
        raise StorageError(message) from None
    return factory(locations)
