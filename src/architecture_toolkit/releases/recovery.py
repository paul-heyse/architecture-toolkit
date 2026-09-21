"""Completing or clearing a publication that crashed between steps seven and eight (DATA-24).

DATA-24 permits a failed publication to leave orphans, and the fault-injection gate proves they
are invisible to a reader. What it does not say is what an operator does next, and W4 left that
unanswered: an orphan manifest permanently blocks its own release id — `write_manifest` refuses to
overwrite a published manifest, correctly — and pins versions against vacuum forever, with no
operation to finish or clear it.

**An orphan is only detectable because the manifest chain links.** Before `parent_release_id` was
populated, "a manifest nobody points at" was indistinguishable from "a superseded manifest", so
this module could not have existed. That is why the two changes landed together.

Two operations, and the asymmetry between them is deliberate:

- `resume` **does not re-stage**. By the time a manifest exists, its versions have been read back
  and verified; the only thing that did not happen is the pointer move. Re-staging would write new
  versions for no reason and produce a release different from the one the manifest describes.
- `discard` refuses anything reachable. A manifest that is current, or that another manifest names
  as its parent, is part of the history whatever else is true of it.
"""

import shutil
from collections.abc import Iterable

from architecture_toolkit.releases.errors import ReleaseError, StaleParentError
from architecture_toolkit.releases.lock import publication_lock
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.publication import verify_against_storage
from architecture_toolkit.releases.reader import read_table_set
from architecture_toolkit.releases.store import ReleaseStore

__all__ = ["discard", "is_orphan", "orphans", "resume"]


def orphans(store: ReleaseStore) -> tuple[str, ...]:
    """Every manifest that is neither current nor named as a parent.

    Exactly the state a crash between steps seven and eight leaves: a complete, verified manifest
    that no reader will ever open, because readers follow the pointer and the chain.
    """
    current = store.current_id()
    referenced = {
        manifest.parent_release_id
        for manifest in store.iter_manifests()
        if manifest.parent_release_id is not None
    }
    return tuple(
        release_id
        for release_id in store.release_ids()
        if release_id != current and release_id not in referenced
    )


def is_orphan(store: ReleaseStore, release_id: str) -> bool:
    return release_id in orphans(store)


def resume(store: ReleaseStore, release_id: str) -> ArchitectureRelease:
    """Finish a publication that got as far as writing its manifest.

    Re-verifies the manifest against storage with the *same* code publication's sixth step uses,
    then moves the pointer. A second implementation of "does this manifest match storage" would be
    a second definition of correct, and the two would eventually disagree.

    Refuses unless the manifest's parent is the current release. Resuming past a pointer that has
    since moved on would rewind the store to an older history — which is the stale-parent failure
    wearing a different hat, so it raises the same error.
    """
    manifest = store.read_manifest(release_id)
    current = store.current_id()

    if current == release_id:
        message = f"release {release_id!r} is already current; there is nothing to resume"
        raise ReleaseError(message)
    if manifest.parent_release_id != current:
        message = (
            f"cannot resume {release_id!r}: it was built on {manifest.parent_release_id!r} and "
            f"the current release is {current!r}. Publish a new release instead of rewinding."
        )
        raise StaleParentError(message)

    with publication_lock(store.lock_path):
        findings = verify_against_storage(manifest, read_table_set(store, manifest))
        if findings:
            codes = sorted({finding.code for finding in findings})
            message = (
                f"cannot resume {release_id!r}: its pinned versions no longer match what it "
                f"claims ({codes}). Discard it and publish again."
            )
            raise ReleaseError(message)
        store.set_current(manifest)
    return manifest


def discard(store: ReleaseStore, release_id: str) -> ArchitectureRelease:
    """Remove an orphan manifest and its artifacts.

    The Delta versions it pinned are deliberately **not** removed. They may be shared with a
    release that is still retained — DATA-22's reuse means two manifests routinely name the same
    version — so deciding what is now unreferenced is `retention.py`'s job, which computes it from
    the manifests that remain rather than guessing from the one being removed.
    """
    manifest = store.read_manifest(release_id)
    if store.current_id() == release_id:
        message = f"release {release_id!r} is current; a current release is not discardable"
        raise ReleaseError(message)

    children = _children(store, release_id)
    if children:
        message = (
            f"release {release_id!r} is the parent of {sorted(children)}; discarding it would "
            "break their chain"
        )
        raise ReleaseError(message)

    store.manifest_path(release_id).unlink()
    artifacts = store.artifact_dir(release_id)
    if artifacts.is_dir():
        shutil.rmtree(artifacts)
    return manifest


def _children(store: ReleaseStore, release_id: str) -> Iterable[str]:
    return {
        manifest.release_id
        for manifest in store.iter_manifests()
        if manifest.parent_release_id == release_id
    }
