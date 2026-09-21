"""Delta history and the change feed, as storage evidence (DATA-57).

`ARCH-TOOL-DATA-001` §11H is unambiguous about what these are for — "debugging, storage-forensics,
verifying which rows/files a storage operation changed, cross-checking the toolkit's semantic-diff
implementation" — and about what they are not: "Do not use them as the architectural change
narrative. Architectural history is still defined by stable IDs, semantic diffs, rationale,
decisions and release manifests."

The distinction is not pedantry. Delta's history says a file was rewritten; it cannot say a
capability was retired, and it will happily report eleven commits for a change that means one
thing. `domain/semantics.semantic_delta` is the architectural answer and W6 classifies it; this
module exists to *cross-check* that answer against what storage actually did, which is a genuinely
useful thing a storage log can do.

Types are returned rather than raw dictionaries so a caller cannot accidentally treat a history
entry as a change record — `CommitAudit` has no field that could be mistaken for one.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pyarrow as pa

from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.provenance import COMMIT_METADATA_FIELDS
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage import delta

__all__ = [
    "CommitAudit",
    "attempts_for",
    "changed_row_counts",
    "commit_audit",
    "table_audit",
]


@dataclass(frozen=True, slots=True)
class CommitAudit:
    """One Delta commit, as storage forensics.

    `provenance` holds the DATA-53 fields the publication attached, which is what makes a commit
    traceable to the attempt that wrote it. Everything else is Delta's own.
    """

    version: int
    operation: str
    provenance: Mapping[str, str]

    @property
    def publication_attempt_id(self) -> str | None:
        return self.provenance.get("publication_attempt_id")


def commit_audit(entry: Mapping[str, object]) -> CommitAudit:
    """One history entry, with the toolkit's provenance separated from Delta's own fields."""
    return CommitAudit(
        version=int(str(entry.get("version", -1))),
        operation=str(entry.get("operation", "")),
        provenance={field: str(entry[field]) for field in COMMIT_METADATA_FIELDS if field in entry},
    )


def table_audit(store: ReleaseStore, table_id: TableId, *, version: int) -> tuple[CommitAudit, ...]:
    """The commit history of one table up to one version, newest first."""
    return tuple(
        commit_audit(entry)
        for entry in delta.history(store.table_location(table_id), version=version)
    )


def changed_row_counts(
    store: ReleaseStore, table_id: TableId, *, base_version: int, candidate_version: int
) -> Mapping[str, int]:
    """How many rows the change feed says were inserted, deleted or updated between two versions.

    The cross-check `ARCH-TOOL-DATA-001` §11H asks for. It answers "did storage move as much as
    the semantic diff says it did", and a disagreement is a bug in one of them — usually a sign
    that a full-snapshot overwrite rewrote rows whose values never changed, which is exactly the
    kind of thing a semantic digest is supposed to ignore and a storage log is not.
    """
    if base_version >= candidate_version:
        return {}
    feed = delta.change_feed(
        store.table_location(table_id),
        version=candidate_version,
        starting_version=base_version + 1,
        ending_version=candidate_version,
    )
    return _tally(feed)


def _tally(feed: pa.Table) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for kind in feed.column("_change_type").to_pylist():
        counts[str(kind)] = counts.get(str(kind), 0) + 1
    return counts


def attempts_for(
    store: ReleaseStore, manifest: ArchitectureRelease
) -> Mapping[TableId, Sequence[str]]:
    """Which publication attempts wrote each table version this release pins.

    Traceability in the direction an operator actually asks for it: not "what did this commit do"
    but "which attempt produced the thing I am reading".
    """
    return {
        ref.table_id: tuple(
            audit.publication_attempt_id
            for audit in table_audit(store, ref.table_id, version=ref.delta_version)
            if audit.publication_attempt_id is not None
        )
        for ref in manifest.tables
    }
