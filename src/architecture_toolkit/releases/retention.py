"""Retention that cannot invalidate a release (DATA-25, DATA-58).

> Never vacuum a Delta version referenced by a retained release or milestone archive.
> — `docs/contracts/data.md`

The whole safety mechanism is deltalake's `vacuum(keep_versions=...)`, and the only thing this
module adds is the list — computed from the manifests themselves rather than from a policy
number somebody has to keep in their head. So "never vacuum a version a retained release needs"
is a *computation*, and the failure mode where a correct policy is applied to a stale idea of
which releases exist cannot happen.

**Nothing is vacuumed by default and no release is ever dropped.** A retention count would be a
number to get wrong, and the volumes here do not justify one: the protected set is every version
every manifest in the store pins. Vacuum is an explicit operation, dry-run by default, and it
refuses outright if its own keep-list would not protect something. Milestone archives are the
answer to disk growth, because they are self-contained and do not depend on the live Delta
directory staying intact.

`probe_readability` is the other half: retention that was safe is not the same as retention that
*is* safe, and a release that has become unreadable — by a vacuum run outside this module, or a
directory somebody moved — is a fact worth surfacing rather than discovering at read time.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.releases.errors import RetentionSafetyError
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage import delta
from architecture_toolkit.validation.diagnostics import Diagnostic
from architecture_toolkit.validation.release import unreadable_versions

__all__ = [
    "RetentionPlan",
    "probe_readability",
    "referenced_versions",
    "retention_plan",
    "vacuum_table",
]


def referenced_versions(store: ReleaseStore) -> Mapping[TableId, frozenset[int]]:
    """Every version every retained manifest pins, by table.

    The input to every decision this module makes. A release that is no longer current still
    counts: DATA-58 protects "every Delta version required by a retained ArchitectureRelease
    manifest", and a manifest is retained until somebody deletes it.
    """
    protected: dict[TableId, set[int]] = {}
    for manifest in store.iter_manifests():
        for table_id, version in manifest.pinned_versions:
            protected.setdefault(table_id, set()).add(version)
    return {table_id: frozenset(versions) for table_id, versions in protected.items()}


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    """What a vacuum would protect and what it would remove. Inspectable before it runs."""

    table_id: TableId
    keep_versions: tuple[int, ...]
    removable_files: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.removable_files


def retention_plan(store: ReleaseStore, table_id: TableId) -> RetentionPlan:
    """What vacuuming this table would do, without doing it.

    A dry run against the real keep-list, so the answer is the one the real call would give
    rather than an estimate of it.
    """
    keep = sorted(referenced_versions(store).get(table_id, frozenset()))
    location = store.table_location(table_id)
    if not delta.is_table(location):
        return RetentionPlan(table_id=table_id, keep_versions=tuple(keep), removable_files=())
    files = delta.vacuum(location, version=delta.tip(location), keep_versions=keep, dry_run=True)
    return RetentionPlan(table_id=table_id, keep_versions=tuple(keep), removable_files=tuple(files))


def vacuum_table(store: ReleaseStore, table_id: TableId, *, apply: bool = False) -> RetentionPlan:
    """Vacuum one table, protecting every referenced version (DATA-58).

    Refuses when the store holds manifests but none of them pins this table: that combination
    means either the table is not part of any release, or the caller is looking at the wrong
    store — and vacuuming on either reading would be destroying something for no reason.
    """
    protected = referenced_versions(store)
    if store.release_ids() and table_id not in protected:
        message = (
            f"{len(store.release_ids())} release(s) exist and none pins {table_id!r}; "
            "refusing to vacuum a table no manifest describes"
        )
        raise RetentionSafetyError(message)

    plan = retention_plan(store, table_id)
    if not apply or plan.is_empty:
        return plan

    location = store.table_location(table_id)
    removed = delta.vacuum(
        location,
        version=delta.tip(location),
        keep_versions=list(plan.keep_versions),
        dry_run=False,
    )
    unreadable = probe_readability(store)
    if unreadable:
        message = (
            f"vacuuming {table_id!r} made {len(unreadable)} pinned version(s) unreadable; "
            "the keep-list and the operation disagree, which is a bug rather than a policy call"
        )
        raise RetentionSafetyError(message)
    return RetentionPlan(
        table_id=table_id, keep_versions=plan.keep_versions, removable_files=tuple(removed)
    )


def probe_readability(store: ReleaseStore) -> tuple[Diagnostic, ...]:
    """Can every retained manifest still open every version it pins?

    Reported as diagnostics rather than raised, because by the time this is false the damage is
    done and the useful act is to say which release and which table.
    """
    broken: dict[str, str] = {}
    for manifest in store.iter_manifests():
        for ref in manifest.tables:
            location = store.resolve(ref.uri)
            try:
                delta.read_version(location, version=ref.delta_version)
            except Exception as error:
                broken[f"{manifest.release_id}/{ref.table_id}"] = (
                    f"{type(error).__name__}: {str(error)[:120]}"
                )
    return unreadable_versions(broken)
