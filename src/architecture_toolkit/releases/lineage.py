"""Which releases are revisions of which, and which are alternatives (DATA-28).

`parent_release_id` has been written by every publication since W4 and read back by nothing: the
publication protocol checks the *expected* parent before writing, and after that the chain is
recorded rather than interpreted. This module is the read side, and it exists because DATA-28 turns
on a distinction that is invisible without it —

> Alternatives/scenarios have separate model/scenario identity plus explicit baseline, not
> sequential release semantics. — data.md

A revision supersedes its parent. An alternative does not supersede anything: it is a different
candidate architecture derived from a common baseline, and *"its existence does not imply that it
superseded or was selected over the current design"* (`ARCH-TOOL-DATA-001` §6B). Two releases can
therefore be comparable without one being a later version of the other, and a diff that did not know
the difference would present an alternative as a change somebody made.
"""

from collections.abc import Iterator

from architecture_toolkit.releases.errors import ReleaseError
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.store import ReleaseStore

__all__ = [
    "ancestors",
    "is_ancestor",
    "lineage_of",
    "require_same_line",
]


def ancestors(store: ReleaseStore, manifest: ArchitectureRelease) -> Iterator[ArchitectureRelease]:
    """Walk `parent_release_id` from the release to the root of its own line, newest first.

    Stops at a parent the store does not hold rather than raising, because a store trimmed by
    retention legitimately loses old manifests and a caller asking "is this a revision of that"
    should get "not as far as this store knows" rather than an exception.

    Refuses a cycle. `validation/release.py::chain_breaks` already reports one as a diagnostic;
    here it would be an infinite loop, so it is a refusal instead.
    """
    seen = {manifest.release_id}
    current = manifest
    while current.parent_release_id is not None:
        parent_id = current.parent_release_id
        if parent_id in seen:
            message = f"release chain through {manifest.release_id!r} revisits {parent_id!r}"
            raise ReleaseError(message)
        if not store.has_manifest(parent_id):
            return
        seen.add(parent_id)
        current = store.read_manifest(parent_id)
        yield current


def lineage_of(store: ReleaseStore, manifest: ArchitectureRelease) -> tuple[str, ...]:
    """The release and its ancestors, newest first."""
    return (manifest.release_id, *(item.release_id for item in ancestors(store, manifest)))


def is_ancestor(
    store: ReleaseStore, candidate: ArchitectureRelease, *, of: ArchitectureRelease
) -> bool:
    """Whether `candidate` is a release `of` was built on top of, however indirectly."""
    return candidate.release_id in {item.release_id for item in ancestors(store, of)}


def require_same_line(base: ArchitectureRelease, candidate: ArchitectureRelease) -> None:
    """Refuse a pair whose relation is "alternative", not "revision".

    The refusal names the operation that *is* right for the pair, because an operator who asked for
    a diff between a baseline and an alternative has asked a reasonable question with the wrong
    verb, and an error that only says "no" leaves them to guess.
    """
    if base.model_id != candidate.model_id:
        message = (
            f"{base.release_id!r} and {candidate.release_id!r} are revisions of different models "
            f"({base.model_id!r} and {candidate.model_id!r}); there is no change between them"
        )
        raise ReleaseError(message)
    if base.scenario_id != candidate.scenario_id:
        message = (
            f"{base.release_id!r} is on line {base.scenario_id or 'baseline'!r} and "
            f"{candidate.release_id!r} is on line {candidate.scenario_id or 'baseline'!r}. "
            f"An alternative is not a later revision of its baseline; compare them as "
            f"alternatives instead of diffing them."
        )
        raise ReleaseError(message)
