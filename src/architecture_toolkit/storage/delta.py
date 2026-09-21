"""The single module that talks to Delta (DATA-22, DATA-51..DATA-58).

`docs/implementation-contract.md` splits the packages so that `storage` owns "Delta persistence"
and `releases` owns "manifest, semantic diff, migration, lock/staging/publication". This module is
what makes that split real rather than aspirational: **every `deltalake` call in the toolkit lives
here**, and `rules/releases-no-direct-delta.yml` stops the release layer reaching past it. The
release layer orchestrates a protocol; it never touches a storage engine.

Almost everything here is a thin, typed wrapper, and deliberately so. The probes behind W4 found
that deltalake already supplies what the data contract asks for — commit provenance that survives
into `history()`, application transaction markers, `keep_versions` on vacuum, row-local check
constraints, a change data feed, and schema-overwrite migrations that leave old versions readable
under their old schema. Wrapping those is the right amount of code. Reimplementing any of them
would be the wrong amount.

**One deliberate exception to the explicit-version rule.** `tip()` is the only place in the
toolkit that passes `version=None`, which asks Delta for the latest. Invariant 5 forbids a
*published release* resolving an implicit latest version, and `tip` is not that: it is a writer
asking what it just committed, under the publication lock, so it can record the exact number in a
manifest. `tests/unit/test_layering.py` asserts it stays the only one.

One behaviour is worth stating because it shapes the caller: **deltalake records an application
transaction marker but does not act on it.** Replaying the same `Transaction(app_id, version)` is
accepted and produces a second commit. `committed_attempt()` reads the marker back so the caller
can skip; the skip is ours, the marker is the library's. See `releases/staging.py`.
"""

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final, Literal

import pyarrow as pa
from deltalake import CommitProperties, DeltaTable, Transaction, write_deltalake

from architecture_toolkit.storage.interchange import as_table

__all__ = [
    "CHANGE_DATA_FEED",
    "add_constraints",
    "change_feed",
    "committed_attempt",
    "constraints",
    "create_empty",
    "history",
    "is_table",
    "open_dataset",
    "open_reader",
    "read_version",
    "tip",
    "vacuum",
    "write_snapshot",
]

CHANGE_DATA_FEED: Final[Mapping[str, str]] = {"delta.enableChangeDataFeed": "true"}
"""Configuration applied at table creation. CDF is storage audit evidence (DATA-57), and it has to
be switched on before the commits it would describe, so it is a creation-time decision."""

_CONSTRAINT_PREFIX: Final[str] = "delta.constraints."


def is_table(location: Path | str) -> bool:
    """Whether a Delta table already exists here. Never creates one."""
    return DeltaTable.is_deltatable(str(location))


def tip(location: Path | str) -> int:
    """The latest committed version of a table.

    The one `version=None` in the toolkit. Invariant 5 is about a published release resolving an
    implicit latest version; this is a writer reading back the number it just created, under the
    publication lock, so that the manifest can pin it explicitly. Everything a *reader* does goes
    through `read_version`.
    """
    return DeltaTable(location, version=None).version()


def read_version(location: Path | str, *, version: int) -> pa.Table:
    """One table at exactly one version. The only read path."""
    return DeltaTable(location, version=version).to_pyarrow_table()


def open_dataset(location: Path | str, *, version: int) -> pa.dataset.Dataset:
    """A lazy PyArrow dataset over one pinned version (DATA-52's preferred candidate).

    Laziness does not relax the pin: a dataset built from `version=0` reads version 0 even after
    the table has moved on, which the qualification tests assert rather than assume.
    """
    return DeltaTable(location, version=version).to_pyarrow_dataset()


def open_reader(location: Path | str, *, version: int) -> object:
    """A single-pass Arrow stream over one pinned version (DATA-43's streaming candidate).

    Returned as `object` because it is an **arro3** reader, not a pyarrow one;
    `storage/interchange.py` is where it becomes a pyarrow value. Typing it as pyarrow here would
    be a lie that happens to work until it does not.
    """
    return DeltaTable(location, version=version).scan()


def write_snapshot(
    location: Path | str,
    table: pa.Table,
    *,
    commit_metadata: Mapping[str, str],
    app_id: str | None = None,
    attempt: int | None = None,
    schema_mode: Literal["overwrite"] | None = None,
    configuration: Mapping[str, str] | None = None,
) -> int:
    """Write a complete replacement snapshot and return the version it created.

    DATA-22's baseline write: a full overwrite of a changed table, never a MERGE and never a
    replay of micro-edits.

    `schema_mode` is typed `Literal["overwrite"] | None`, which is DATA-56 expressed as a type
    rather than a rule: deltalake also accepts `"merge"`, and a caller reaching for it fails
    `pyrefly check` instead of silently making automatic schema merge the publication behaviour
    the requirement forbids. Ordinary publication passes `None`; only a declared migration passes
    `"overwrite"`.

    The app transaction marker is attached when `app_id` and `attempt` are given. It makes the
    write *identifiable* on retry; it does not make it idempotent. The caller checks
    `committed_attempt` first.
    """
    commit_properties = CommitProperties(
        custom_metadata=dict(commit_metadata),
        app_transactions=(
            [Transaction(app_id=app_id, version=attempt)]
            if app_id is not None and attempt is not None
            else None
        ),
    )
    # Branched rather than passing a computed `mode`, because the two calls have different
    # overloads and the literal is what makes the checker able to tell them apart.
    if is_table(location):
        write_deltalake(
            location,
            table,
            mode="overwrite",
            schema_mode=schema_mode,
            commit_properties=commit_properties,
        )
    else:
        write_deltalake(
            location,
            table,
            mode="error",
            schema_mode=schema_mode,
            configuration=dict(configuration or CHANGE_DATA_FEED),
            commit_properties=commit_properties,
        )
    return tip(location)


def committed_attempt(location: Path | str, *, app_id: str, version: int) -> int | None:
    """The highest attempt this app id has committed to this table, or `None`.

    Reads the marker deltalake wrote. `version` pins the table state being asked about, which
    keeps this on the explicit-version path like every other read.
    """
    return DeltaTable(location, version=version).transaction_version(app_id)


def history(location: Path | str, *, version: int) -> list[Mapping[str, object]]:
    """Commit history up to one version (DATA-57).

    Storage forensics, not the architectural change narrative. The DATA-53 provenance fields
    appear as top-level keys of each entry — measured, not assumed.
    """
    return list(DeltaTable(location, version=version).history())


def change_feed(
    location: Path | str, *, version: int, starting_version: int, ending_version: int | None = None
) -> pa.Table:
    """The change data feed between two versions (DATA-57).

    Requires `delta.enableChangeDataFeed`, which `write_snapshot` sets at creation. Returns rows
    carrying `_change_type`, `_commit_version` and `_commit_timestamp`. A cross-check on the
    semantic diff, never a substitute for it.
    """
    reader = DeltaTable(location, version=version).load_cdf(
        starting_version=starting_version, ending_version=ending_version
    )
    return as_table(reader)


def vacuum(
    location: Path | str,
    *,
    version: int,
    keep_versions: Sequence[int],
    dry_run: bool = True,
    retention_hours: int = 0,
) -> list[str]:
    """Remove files no retained version needs, protecting the ones that are named (DATA-58).

    `keep_versions` is the whole safety mechanism and it is the library's, not ours: deltalake
    narrows deletion to files no kept version references. The caller computes that list from the
    manifests in the store, so "never vacuum a version a retained release needs" is a computation
    rather than a hope.

    `retention_hours=0` with `enforce_retention_duration=False` is deliberate: the default
    week-long window protects against *concurrent readers*, which the one-writer contract already
    excludes, and leaving it on would make the keep-list untestable without sleeping for a week.
    """
    return DeltaTable(location, version=version).vacuum(
        retention_hours=retention_hours,
        dry_run=dry_run,
        enforce_retention_duration=False,
        keep_versions=list(keep_versions),
    )


def add_constraints(location: Path | str, *, version: int, expressions: Mapping[str, str]) -> None:
    """Attach row-local check constraints (DATA-55).

    Only row-local invariants belong here. Endpoint validity, cross-table referential rules, graph
    and cardinality semantics, evidence requirements and release coherence need application
    context that a per-row SQL predicate does not have, and `storage/constraints.py` is where that
    boundary is written down and guarded.
    """
    if not expressions:
        return
    DeltaTable(location, version=version).alter.add_constraint(dict(expressions))


def constraints(location: Path | str, *, version: int) -> Mapping[str, str]:
    """The check constraints currently on a table, by name."""
    configuration = DeltaTable(location, version=version).metadata().configuration
    return {
        key.removeprefix(_CONSTRAINT_PREFIX): value
        for key, value in configuration.items()
        if key.startswith(_CONSTRAINT_PREFIX)
    }


def create_empty(
    location: Path | str,
    schema: pa.Schema,
    *,
    configuration: Iterable[tuple[str, str]] | None = None,
) -> int:
    """Create a typed empty table at version 0 (§11B typed empties).

    A table with no rows is not a table with no schema, and creating one explicitly is how a
    release can pin a table that has never had content.
    """
    DeltaTable.create(
        location,
        schema,
        configuration=dict(configuration) if configuration is not None else dict(CHANGE_DATA_FEED),
    )
    return tip(location)
