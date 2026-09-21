"""Delta history and the change feed, as storage evidence (DATA-57).

`ARCH-TOOL-DATA-001` §11H is unambiguous about what these are for — "debugging, storage-forensics,
verifying which rows/files a storage operation changed, cross-checking the toolkit's semantic-diff
implementation" — and about what they are not: "Do not use them as the architectural change
narrative. Architectural history is still defined by stable IDs, semantic diffs, rationale,
decisions and release manifests."

The distinction is not pedantry. Delta's history says a file was rewritten; it cannot say a
capability was retired, and it will happily report a commit per table for a change that means one
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
    "net_row_changes",
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


# Delta spells an update as a pre/post image pair when a table is written with MERGE, and as a
# plain delete/insert pair under the full-snapshot overwrite this toolkit uses. Both spellings are
# named so the netting does not depend on which write path produced the feed.
_REMOVING = frozenset({"delete", "update_preimage"})
_ADDING = frozenset({"insert", "update_postimage"})


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


def net_row_changes(
    store: ReleaseStore,
    table_id: TableId,
    identity_field: str,
    *,
    base_version: int,
    candidate_version: int,
) -> Mapping[str, tuple[str, ...]]:
    """Which *identities* the change feed says moved, after cancelling the rows that did not.

    `changed_row_counts` answers how much storage moved, and the answer is deliberately larger than
    the semantic diff — publication writes full snapshots (DATA-22), so renaming one element
    rewrites every row of `elements` and the feed reports each one as a delete and an insert.
    Measured on the example model: one semantic change, twenty change-feed rows.

    Netting is what makes the two comparable. A row identical in `(identity, content_hash)` on both
    sides of the rewrite cancels; what survives is exactly the added, removed and changed
    identities, which is the same question `semantic_delta` answers from the other direction. That
    is the cross-check §11H asks for, and it is a cross-check rather than a narrative because it
    cannot say *what* changed inside a record — only that the stamped digest moved.

    Empty when the table was reused: an unmoved pin means storage did nothing to compare.
    """
    if base_version >= candidate_version:
        return {"added": (), "removed": (), "changed": ()}
    feed = delta.change_feed(
        store.table_location(table_id),
        version=candidate_version,
        starting_version=base_version + 1,
        ending_version=candidate_version,
    )
    rows = feed.select([identity_field, "content_hash", "_change_type"]).to_pylist()
    deleted = {
        (str(row[identity_field]), str(row["content_hash"]))
        for row in rows
        if str(row["_change_type"]) in _REMOVING
    }
    inserted = {
        (str(row[identity_field]), str(row["content_hash"]))
        for row in rows
        if str(row["_change_type"]) in _ADDING
    }
    gone = {identity for identity, _ in deleted - inserted}
    arrived = {identity for identity, _ in inserted - deleted}
    return {
        "added": tuple(sorted(arrived - gone)),
        "removed": tuple(sorted(gone - arrived)),
        "changed": tuple(sorted(gone & arrived)),
    }
