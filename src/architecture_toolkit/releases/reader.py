"""Opening exactly the versions a manifest names (DATA-21, DATA-51).

`ARCH-TOOL-DATA-001` §5C puts it plainly: "Readers load the manifest once and open exactly the
table versions it names. They never assemble a model by independently reading each table's latest
state." This module is that sentence, executable.

Every read goes through a `SnapshotProvider`, so DATA-51's promise holds — interoperability can
change without touching release semantics. The provider is a parameter with the materialized
default, which is the only thing DATA-52 lets be a default until the others have passed the full
matrix.

Metadata is reattached on the way in because Delta drops schema-level keys and keeps field-level
ones. That is a repair, not an interpretation: `storage/mappings.py` never reads metadata, and a
table stripped of every key produces identical records and identical digests.
"""

from collections.abc import Mapping

import pyarrow as pa

from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.domain.model import Model
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.mappings import TableSet, assemble_model
from architecture_toolkit.storage.metadata import reattach
from architecture_toolkit.storage.schemas import STORAGE_SCHEMA_VERSION, TABLE_SCHEMAS
from architecture_toolkit.storage.snapshot import MaterializedPyArrowSnapshotProvider

__all__ = [
    "is_current_storage_schema",
    "provider_for",
    "read_model",
    "read_table_set",
    "storage_schema_version_of",
]


def provider_for(
    store: ReleaseStore, manifest: ArchitectureRelease
) -> MaterializedPyArrowSnapshotProvider:
    """A provider whose locations come from the manifest, not from a convention.

    `storage/snapshot.py` reserved this: "W4 builds the mapping from a release manifest". A
    provider that resolved a path by convention could resolve a wrong one, and would make a
    manifest's `uri` decorative.
    """
    return MaterializedPyArrowSnapshotProvider(
        {ref.table_id: store.resolve(ref.uri) for ref in manifest.tables}
    )


def read_table_set(
    store: ReleaseStore,
    manifest: ArchitectureRelease,
    *,
    provider: MaterializedPyArrowSnapshotProvider | None = None,
) -> TableSet:
    """The eleven tables of one release, each at the version the manifest pins."""
    reader = provider if provider is not None else provider_for(store, manifest)
    tables: Mapping[TableId, pa.Table] = {
        ref.table_id: reattach(
            reader.read(ref.table_id, version=ref.delta_version), TABLE_SCHEMAS[ref.table_id]
        )
        for ref in manifest.tables
    }
    return TableSet(
        model_id=manifest.model_id,
        schema_version=manifest.schema_version,
        profile_version=manifest.profile_version,
        storage_schema_version=manifest.generator.storage_schema_version,
        tables=tables,
    )


def read_model(
    store: ReleaseStore,
    manifest: ArchitectureRelease,
    *,
    provider: MaterializedPyArrowSnapshotProvider | None = None,
) -> Model:
    """One release as a validated model.

    `assemble_model` re-runs every record-local validator, so a release that was written by an
    older toolkit and no longer validates fails here rather than being handed back as if it were
    still coherent.
    """
    return assemble_model(read_table_set(store, manifest, provider=provider))


def storage_schema_version_of(manifest: ArchitectureRelease) -> str:
    """Which physical schema this release was written against (the DATA-56 migration anchor)."""
    return manifest.generator.storage_schema_version


def is_current_storage_schema(manifest: ArchitectureRelease) -> bool:
    return storage_schema_version_of(manifest) == STORAGE_SCHEMA_VERSION
