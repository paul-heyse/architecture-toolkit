"""Explicit, versioned schema migrations (DATA-56).

> Schema changes are versioned migrations with old/new schema/profile versions; a migration
> function/process; a historical replay test; compatibility/expected change assertions.
> Do not rely on automatic schema merge as normal publication behavior.
> — `docs/contracts/data.md`

The last sentence is enforced by a type rather than by this module: `storage.delta.write_snapshot`
declares `schema_mode: Literal["overwrite"] | None`, so the `"merge"` deltalake also accepts fails
`pyrefly check`. A migration passes `"overwrite"` deliberately and is the only caller that passes
anything.

**A migration does not rewrite history.** It writes *new* versions; every version a retained
manifest pins keeps reading under the schema it was written with, which is the property
`historical_replay` asserts and the reason DATA-58's protected set is computed from manifests
rather than from a cutoff. An earlier release stays queryable after an intentional schema
migration — §10E — because nothing about it changed.

`MIGRATIONS` is **empty**, and that is the honest state: `STORAGE_SCHEMA_VERSION` is `1.0.0` and
nothing has been published against an earlier one, so there is no migration to declare. The
machinery is real and exercised end to end by a synthetic `1.0.0 -> 1.1.0` migration in
`tests/integration/test_migration.py`. Inventing a production schema change to make the registry
non-empty would be making up work to demonstrate machinery.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import pyarrow as pa

from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.releases.errors import MigrationError
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.mappings import mapping_for

__all__ = [
    "MIGRATIONS",
    "Migration",
    "MigrationResult",
    "apply_migration",
    "historical_replay",
    "migration_for",
]

type Transform = Callable[[TableId, pa.Table], pa.Table]


def _unchanged(table_id: TableId, table: pa.Table) -> pa.Table:
    """The identity transform, and the default.

    A migration that only adds a table rewrites nothing, and saying that with an empty `tables`
    tuple is clearer than requiring every such declaration to supply a function it never calls.
    """
    del table_id
    return table


@dataclass(frozen=True, slots=True)
class Migration:
    """One declared step between two storage schema versions.

    `tables` is explicit rather than "whatever changed": a migration that silently touched a table
    nobody listed would be indistinguishable from a bug, and the expected-change assertion
    DATA-56 asks for needs something to compare against.
    """

    migration_id: str
    from_storage_schema_version: str
    to_storage_schema_version: str
    description: str
    tables: tuple[TableId, ...] = ()
    transform: Transform = _unchanged
    added_tables: tuple[TableId, ...] = ()
    """Tables this version introduces, which the `from` version's releases never pinned.

    Separate from `tables`, and that separation is the design rather than bookkeeping. A
    `Transform` takes the existing table and returns the new one — for a table being added there
    is no existing one to take, and `apply_migration` cannot even find it, because it looks the
    old version up through `manifest.table(table_id)` and the old manifest never pinned it.

    More importantly the content is not a matter of choice. A release published before the table
    existed had no rows for it, so the only honest content is the declared schema with zero rows.
    Inventing rows would be fabricating architecture, which is why this is a declaration rather
    than a second transform hook.
    """

    def __post_init__(self) -> None:
        overlap = sorted(set(self.tables) & set(self.added_tables))
        if overlap:
            message = f"migration {self.migration_id!r} both rewrites and adds {overlap}"
            raise MigrationError(message)
        if not self.tables and not self.added_tables:
            message = f"migration {self.migration_id!r} declares no table to rewrite or add"
            raise MigrationError(message)

    def applies_to(self, manifest: ArchitectureRelease) -> bool:
        return manifest.generator.storage_schema_version == self.from_storage_schema_version


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """What a migration did, per table: the version before and the version it wrote."""

    migration_id: str
    versions: Mapping[TableId, tuple[int | None, int]]
    """`(before, after)` per table. `before` is `None` for a table this migration created.

    `None` rather than `-1` or `0`: a table that did not exist has no previous version, and every
    reader is now forced to say what it does about that rather than comparing against a number
    that looks like a real Delta version.
    """

    @property
    def migrated_tables(self) -> tuple[TableId, ...]:
        return tuple(sorted(self.versions))

    @property
    def created_tables(self) -> tuple[TableId, ...]:
        """The tables this migration brought into existence, as opposed to rewrote."""
        return tuple(sorted(name for name, (before, _) in self.versions.items() if before is None))


MIGRATIONS: Final[Mapping[str, Migration]] = MappingProxyType({})
"""Empty at W4 because `STORAGE_SCHEMA_VERSION` has only ever been `1.0.0`. See the module
docstring for why that is the honest state rather than a gap."""


def migration_for(from_version: str, to_version: str) -> Migration:
    """The declared step between two storage schema versions, or `MigrationError`.

    There is no chaining and no inference. DATA-56 asks for *explicit* versioned migrations, and a
    runner that composed two steps it was never told compose would be inferring exactly the thing
    the requirement wants stated.
    """
    for migration in MIGRATIONS.values():
        if (
            migration.from_storage_schema_version == from_version
            and migration.to_storage_schema_version == to_version
        ):
            return migration
    message = f"no declared migration from storage schema {from_version} to {to_version}"
    raise MigrationError(message)


def apply_migration(
    store: ReleaseStore,
    migration: Migration,
    manifest: ArchitectureRelease,
    *,
    commit_metadata: Mapping[str, str] | None = None,
) -> MigrationResult:
    """Apply one migration to the tables of one release, writing new versions.

    The release being migrated is **not** modified: its manifest still pins the versions it always
    pinned and still reads. What this produces is new versions a *future* release can pin, which
    is why a migration and a publication are separate operations.
    """
    if not migration.applies_to(manifest):
        message = (
            f"migration {migration.migration_id!r} starts at storage schema "
            f"{migration.from_storage_schema_version}, and release {manifest.release_id!r} is at "
            f"{manifest.generator.storage_schema_version}"
        )
        raise MigrationError(message)

    metadata = dict(commit_metadata or {}) | {
        "migration_id": migration.migration_id,
        "storage_schema_version": migration.to_storage_schema_version,
        "migrated_from": migration.from_storage_schema_version,
    }
    versions: dict[TableId, tuple[int | None, int]] = {}
    for table_id in migration.added_tables:
        # Not `manifest.table(table_id)`: the old manifest never pinned this, which is the whole
        # point. `to_arrow(())` rather than the bare schema, because `TableMapping.to_arrow`
        # attaches the self-describing metadata, so a migration-created table is byte-identical
        # to a publication-created one.
        location = store.table_location(table_id)
        empty = mapping_for(table_id).to_arrow(())
        versions[table_id] = (
            None,
            delta.write_snapshot(
                location, empty, commit_metadata=metadata, schema_mode="overwrite"
            ),
        )
    for table_id in migration.tables:
        ref = manifest.table(table_id)
        location = store.resolve(ref.uri)
        before = ref.delta_version
        migrated = migration.transform(table_id, delta.read_version(location, version=before))
        after = delta.write_snapshot(
            location, migrated, commit_metadata=metadata, schema_mode="overwrite"
        )
        versions[table_id] = (before, after)
    return MigrationResult(migration_id=migration.migration_id, versions=versions)


def historical_replay(
    store: ReleaseStore, manifest: ArchitectureRelease, *, tables: Sequence[TableId] | None = None
) -> Mapping[TableId, pa.Schema]:
    """Re-read a release at the versions it pins, and report the schema each one still has.

    The DATA-56 replay assertion, and §10E's "an earlier release must remain queryable … including
    after an intentional schema migration". A migrated table's *old* version keeps its old schema,
    which is what makes a retained release readable rather than merely present.
    """
    chosen = tables if tables is not None else [ref.table_id for ref in manifest.tables]
    return {
        table_id: delta.read_version(
            store.resolve(manifest.table(table_id).uri),
            version=manifest.table(table_id).delta_version,
        ).schema
        for table_id in chosen
    }
