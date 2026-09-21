"""Writing the tables a release changed, and reusing the ones it did not (DATA-22, DATA-54).

Two rules do most of the work here, and both are about *not* writing.

**A table whose semantic digest is unchanged is not written at all.** Delta creates a new version
for an identical overwrite — measured — so "reuse existing versions for unchanged tables" cannot
mean "write it again and hope". It means: compare the candidate's per-table digest with the
parent manifest's, and for a match, carry the parent's `delta_version` straight into the new
manifest. A rename moves `elements` and leaves the other ten pins exactly where they were, which
is what makes DATA-21's reuse gate observable in a diff of two manifests.

**An attempt that already committed a table is not written again.** This is DATA-54, and the
honest description of the mechanism matters: deltalake *records* an application transaction
marker and does not act on it. Replaying `Transaction(app_id, version)` is accepted and produces
a second commit. So `transaction_version(app_id)` is read first and the write is skipped when the
attempt is already present. The marker is the library's; the idempotency is ours.

Neither rule makes publication atomic. A table can be staged successfully and the release still
never published — that is the whole point of staging being separate from the pointer move, and
DATA-24 permits exactly those orphans.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.releases.manifest import ArchitectureRelease, TableRef
from architecture_toolkit.releases.provenance import commit_metadata
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.digests import table_set_digests
from architecture_toolkit.storage.mappings import TableSet
from architecture_toolkit.storage.schemas import TABLE_IDS

__all__ = ["APP_ID_PREFIX", "StagedTable", "StagingOutcome", "app_id", "stage_tables"]

APP_ID_PREFIX: Final[str] = "architecture-toolkit/publication/"
"""One application transaction id **per release**, not one shared id with a counter.

The question the marker answers is "has this release already written this table", so the release
is the right key. The counter this replaced was derived from the number of manifests in the store,
which shifts when a failed publication leaves an orphan manifest behind — so a retry after the one
crash the marker exists to survive would have been handed a different number and rewritten every
table. Keying on the release id makes a retry of the same release find its own marker and a
different release not find it, with no state to keep."""


def app_id(release_id: str) -> str:
    return f"{APP_ID_PREFIX}{release_id}"


_MARKER_VERSION: Final[int] = 1
"""Every release writes its marker at version 1, because the app id already identifies it."""


class StagingOutcome(StrEnum):
    """Why a table ended up at the version it did. Recorded so a publication can be explained."""

    WRITTEN = "written"
    """The digest changed, so a full replacement snapshot was committed."""

    REUSED = "reused"
    """The digest matched the parent's, so the parent's version was carried forward (DATA-22)."""

    ALREADY_COMMITTED = "already_committed"
    """This attempt had already written this table; the retry skipped it (DATA-54)."""


@dataclass(frozen=True, slots=True)
class StagedTable:
    """One table's outcome, and the pin that will go into the manifest."""

    table_id: TableId
    delta_version: int
    semantic_digest: str
    row_count: int
    outcome: StagingOutcome

    def as_ref(self, *, uri: str) -> TableRef:
        return TableRef(
            table_id=self.table_id,
            uri=uri,
            delta_version=self.delta_version,
            semantic_digest=self.semantic_digest,
            row_count=self.row_count,
        )


def stage_tables(
    store: ReleaseStore,
    table_set: TableSet,
    *,
    parent: ArchitectureRelease | None,
    release_id: str,
    source_bundle_digest: str,
    generator_commit: str,
    change_set_id: str | None = None,
) -> tuple[StagedTable, ...]:
    """Stage every table of a candidate, writing only what changed.

    `release_id` is both the identity of the work and the retry key: a second call for the same
    release finds its own markers and skips, and a different release does not. That is DATA-54's
    "per-table retry/idempotency" and nothing more — a table can be staged successfully and the
    release still never published.
    """
    digests = table_set_digests(table_set)
    parent_pins = _parent_pins(parent)
    staged: list[StagedTable] = []

    for table_id in TABLE_IDS:
        table = table_set[table_id]
        digest = digests[table_id]
        location = store.table_location(table_id)
        reused = parent_pins.get(table_id)

        if reused is not None and reused.semantic_digest == digest and delta.is_table(location):
            staged.append(
                StagedTable(
                    table_id=table_id,
                    delta_version=reused.delta_version,
                    semantic_digest=digest,
                    row_count=reused.row_count,
                    outcome=StagingOutcome.REUSED,
                )
            )
            continue

        already = _already_committed(location, release_id=release_id)
        if already is not None:
            staged.append(
                StagedTable(
                    table_id=table_id,
                    delta_version=already,
                    semantic_digest=digest,
                    row_count=table.num_rows,
                    outcome=StagingOutcome.ALREADY_COMMITTED,
                )
            )
            continue

        version = delta.write_snapshot(
            location,
            table,
            commit_metadata=commit_metadata(
                publication_attempt_id=release_id,
                model_id=table_set.model_id,
                table_id=table_id,
                profile_version=table_set.profile_version,
                source_bundle_digest=source_bundle_digest,
                generator_commit=generator_commit,
                change_set_id=change_set_id,
                expected_parent_release_id=None if parent is None else parent.release_id,
            ),
            app_id=app_id(release_id),
            attempt=_MARKER_VERSION,
        )
        staged.append(
            StagedTable(
                table_id=table_id,
                delta_version=version,
                semantic_digest=digest,
                row_count=table.num_rows,
                outcome=StagingOutcome.WRITTEN,
            )
        )

    return tuple(staged)


def _parent_pins(parent: ArchitectureRelease | None) -> Mapping[TableId, TableRef]:
    return {} if parent is None else {ref.table_id: ref for ref in parent.tables}


def _already_committed(location: Path, *, release_id: str) -> int | None:
    """The version this release wrote to this table, if it already did (DATA-54).

    `None` for a table that does not exist yet and for a release that has not written it. There is
    no ordering question any more: a marker either belongs to this release or it does not.
    """
    if not delta.is_table(location):
        return None
    version = delta.tip(location)
    seen = delta.committed_attempt(location, app_id=app_id(release_id), version=version)
    return version if seen is not None else None
