"""Immutable release manifests, the publication protocol, retention and milestone archives.

A Delta table version is storage history; an `ArchitectureRelease` is a coherent multi-table
revision of the architecture. This package owns the second and orchestrates the first — every
`deltalake` call lives in `storage/delta.py`, and `rules/releases-no-direct-delta.yml` keeps it
that way.
"""

from architecture_toolkit.releases.candidate import ReleaseCandidate, next_release_id
from architecture_toolkit.releases.errors import (
    ArchiveError,
    MigrationError,
    PublicationLockError,
    ReadBackMismatchError,
    ReleaseError,
    RetentionSafetyError,
    StaleParentError,
    UnknownReleaseError,
)
from architecture_toolkit.releases.lock import publication_lock
from architecture_toolkit.releases.manifest import (
    ArchitectureRelease,
    GeneratorProvenance,
    SourceBundle,
    TableRef,
)
from architecture_toolkit.releases.publication import (
    STEP_ORDER,
    STEPS,
    DeltaPublisher,
    PublicationRequest,
    PublicationState,
    publish,
)
from architecture_toolkit.releases.reader import read_model, read_table_set
from architecture_toolkit.releases.store import DEFAULT_STORE_ROOT, ReleaseStore

__all__ = [
    "DEFAULT_STORE_ROOT",
    "STEPS",
    "STEP_ORDER",
    "ArchitectureRelease",
    "ArchiveError",
    "DeltaPublisher",
    "GeneratorProvenance",
    "MigrationError",
    "PublicationLockError",
    "PublicationRequest",
    "PublicationState",
    "ReadBackMismatchError",
    "ReleaseCandidate",
    "ReleaseError",
    "ReleaseStore",
    "RetentionSafetyError",
    "SourceBundle",
    "StaleParentError",
    "TableRef",
    "UnknownReleaseError",
    "next_release_id",
    "publication_lock",
    "publish",
    "read_model",
    "read_table_set",
]
