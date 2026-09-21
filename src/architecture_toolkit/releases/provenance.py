"""Where a release came from: source identity and commit metadata (DATA-37, DATA-53).

Two questions, answered separately because they are answered by different things.

**What was this authored from? (DATA-37)** The requirement's point is that a mutable URL does not
identify a version. Where a source has an immutable revision, record it; where it does not,
"preserve an authorized snapshot and digest rather than pretending a mutable URL identifies a
version". So `source_bundle` always digests the bytes actually read, and carries a revision only
when one genuinely exists.

**Which publication attempt wrote this table version? (DATA-53)** Delta answers this natively:
`CommitProperties(custom_metadata=...)` keys come back as top-level keys of the matching
`history()` entry — measured, not assumed. So the ten fields the contract lists need no sidecar
store and no table of our own; they travel with the commit that they describe.

Both are deliberately free of anything host-specific beyond what a reader needs: no absolute
paths, no usernames. `scripts/check_boundaries.py` would reject a committed one that carried them,
and a manifest that pinned a `/Users/...` path would stop meaning anything the moment it moved.
"""

import hashlib
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from architecture_toolkit.domain.semantics import SEMANTIC_HASH_VERSION
from architecture_toolkit.releases.manifest import GeneratorProvenance, SourceBundle
from architecture_toolkit.storage.metadata import toolkit_version
from architecture_toolkit.storage.schemas import STORAGE_SCHEMA_VERSION

__all__ = [
    "COMMIT_METADATA_FIELDS",
    "commit_metadata",
    "digest_bytes",
    "generator_provenance",
    "source_bundle",
    "source_revision",
    "toolkit_commit",
]

COMMIT_METADATA_FIELDS: Final[tuple[str, ...]] = (
    "publication_attempt_id",
    "change_set_id",
    "model_id",
    "table_id",
    "expected_parent_release_id",
    "storage_schema_version",
    "profile_version",
    "generator_commit",
    "source_bundle_digest",
    "toolkit_version",
)
"""Exactly the field list `ARCH-TOOL-DATA-001` §11F names. A test asserts the two agree."""

_UNKNOWN_COMMIT: Final[str] = "unknown"


def digest_bytes(payload: bytes) -> str:
    """`sha256:<hex>`, the one digest spelling in this toolkit (`DIGEST_PATTERN`)."""
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def toolkit_commit(root: Path | None = None) -> str:
    """The generator commit, or `"unknown"` outside a checkout.

    Same discipline as `tests/plugins/requirement_evidence.py`: an argv array, never a shell
    string, with a timeout, and a fallback rather than an exception — a release published from an
    exported tarball is still a release, and refusing to publish because git is absent would be
    the wrong failure.
    """
    command = ["git", "rev-parse", "HEAD"]
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return _UNKNOWN_COMMIT
    revision = completed.stdout.strip()
    return revision if completed.returncode == 0 and revision else _UNKNOWN_COMMIT


def source_revision(path: Path) -> str | None:
    """The commit that last changed this file, or `None` when there is not one.

    `None` is the honest answer in three different situations and the caller treats them alike:
    the file is untracked, the directory is not a checkout, or git is absent. DATA-37 is about
    what a revision *means* — where one exists it identifies a version, and where one does not a
    mutable path does not become one by being written down.

    Same argv discipline as `toolkit_commit`: an array, never a shell string, with a timeout and
    a fallback rather than an exception.
    """
    command = ["git", "log", "-1", "--format=%H", "--", path.name]
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=path.parent if path.parent.exists() else None,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None
    revision = completed.stdout.strip()
    return revision if completed.returncode == 0 and revision else None


def generator_provenance(*, commit: str | None = None) -> GeneratorProvenance:
    """Which toolkit produced a release, and under which durable conventions."""
    return GeneratorProvenance(
        toolkit_version=toolkit_version(),
        toolkit_commit=commit if commit is not None else toolkit_commit(),
        storage_schema_version=STORAGE_SCHEMA_VERSION,
        hash_algorithm_version=SEMANTIC_HASH_VERSION,
    )


def source_bundle(
    *,
    source_id: str,
    text: str,
    revision: str | None = None,
    snapshot_path: str | None = None,
) -> SourceBundle:
    """Pin the bytes that were actually read.

    `source_id` is the authored identity — a repository-relative path, not an absolute one — and
    `digest` is over the exact text parsed, so a later reader can tell whether the file on disk is
    still the one the release was built from.
    """
    return SourceBundle(
        source_id=source_id,
        digest=digest_bytes(text.encode("utf-8")),
        revision=revision,
        snapshot_path=snapshot_path,
    )


def commit_metadata(
    *,
    publication_attempt_id: str,
    model_id: str,
    table_id: str,
    profile_version: str,
    source_bundle_digest: str,
    generator_commit: str,
    change_set_id: str | None = None,
    expected_parent_release_id: str | None = None,
) -> Mapping[str, str]:
    """The DATA-53 provenance for one table commit, as Delta custom metadata.

    Absent optional values are omitted rather than written as `"None"`: a first release genuinely
    has no parent, and a history entry claiming `expected_parent_release_id="None"` would be a
    fact nobody stated.
    """
    metadata: dict[str, str] = {
        "publication_attempt_id": publication_attempt_id,
        "model_id": model_id,
        "table_id": table_id,
        "storage_schema_version": STORAGE_SCHEMA_VERSION,
        "profile_version": profile_version,
        "generator_commit": generator_commit,
        "source_bundle_digest": source_bundle_digest,
        "toolkit_version": toolkit_version(),
    }
    if change_set_id is not None:
        metadata["change_set_id"] = change_set_id
    if expected_parent_release_id is not None:
        metadata["expected_parent_release_id"] = expected_parent_release_id
    return metadata
