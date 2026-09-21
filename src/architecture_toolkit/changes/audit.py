"""Cross-checking the semantic diff against what storage actually did (DATA-57).

> Use them for ... cross-checking the toolkit's semantic-diff implementation. Do not use them as
> the architectural change narrative. — `ARCH-TOOL-DATA-001` §11H

Two readings of the same pair of releases, from opposite ends. `semantic_delta` recomputes a
digest from assembled records; the Delta change feed reports the rows a write touched and carries
the `content_hash` those rows were stamped with. They can only agree if the stamped digest and the
recomputed one are the same function — which is precisely the thing that would break silently if
normalization changed and a restamp were missed.

**The netting is what makes them comparable, and it is not a way of making them agree.** Publication
writes full snapshots, so the raw feed reports every row of a rewritten table as a delete and an
insert: on the example model, one semantic change and twenty change-feed rows. `changed_row_counts`
keeps that number, and `tests/integration/test_audit_and_migration.py` keeps asserting the two
differ — that inequality is the DATA-57 lesson, and tightening it would assert the confusion the
requirement forbids. What `net_row_changes` answers is a different question about a different
quantity: which *identities* survived the cancellation, which is the same question the digest
answers.

**Reused tables are silent, and that is correct.** A table whose pin did not move was not written,
so the feed has nothing to say about it — and the digest agrees, because an unwritten table cannot
have changed. The cross-check therefore compares only the tables whose pins moved, and says so
rather than treating silence as agreement.
"""

from collections.abc import Mapping

from architecture_toolkit.domain.semantics import MODEL_COLLECTIONS, semantic_delta
from architecture_toolkit.releases.audit import net_row_changes
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.store import ReleaseStore

__all__ = ["compared_tables", "storage_disagreements"]


def compared_tables(base: ArchitectureRelease, candidate: ArchitectureRelease) -> tuple[str, ...]:
    """The collections whose Delta pin moved between two releases.

    Named separately because "the cross-check found nothing" and "the cross-check compared nothing"
    are different results, and a caller that cannot tell them apart will eventually report the
    second as the first.
    """
    pins = dict(base.pinned_versions)
    later = dict(candidate.pinned_versions)
    return tuple(
        collection
        for collection, _ in MODEL_COLLECTIONS
        if collection in pins and later.get(collection, -1) > pins[collection]
    )


def storage_disagreements(
    store: ReleaseStore, base: ArchitectureRelease, candidate: ArchitectureRelease
) -> tuple[str, ...]:
    """Where the Delta change feed and the semantic digest disagree. Empty means they agree.

    Messages rather than an exception, for the same reason
    `changes/releases.py::identity_disagreements` returns them: the caller decides what a
    disagreement means, and neither a CLI nor a qualification test should have to catch something
    to learn that nothing was wrong.
    """
    moved = set(compared_tables(base, candidate))
    if not moved:
        return ()
    oracle = {
        delta.collection: delta
        for delta in semantic_delta(
            read_model(store, base), read_model(store, candidate)
        ).collections
    }
    found: list[str] = []
    for collection, identity_field in MODEL_COLLECTIONS:
        if collection not in moved:
            continue
        observed = net_row_changes(
            store,
            collection,
            identity_field,
            base_version=base.table(collection).delta_version,
            candidate_version=candidate.table(collection).delta_version,
        )
        expected: Mapping[str, tuple[str, ...]] = {
            "added": tuple(sorted(oracle[collection].added)),
            "removed": tuple(sorted(oracle[collection].removed)),
            "changed": tuple(sorted(oracle[collection].changed)),
        }
        for name, wanted in expected.items():
            if observed[name] != wanted:
                found.append(
                    f"{collection}.{name}: the Delta change feed nets to {observed[name]} and "
                    f"the semantic digest reports {wanted}"
                )
    return tuple(found)
