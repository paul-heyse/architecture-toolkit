"""What release publication refuses, and why each refusal is its own type.

The failures here are operational rather than structural: a caller that catches one has to decide
whether to retry, to rebase on a newer parent, to break a lock or to stop. A single `ReleaseError`
would make those indistinguishable at exactly the moment the distinction matters.

`StaleParentError` and `PublicationLockError` are the two DATA-23 names. Neither is a bug in the
model being published — both say that the *world* moved — which is why they are separate from
`validation/`'s diagnostics, and why a publication that raises them has changed nothing.
"""

__all__ = [
    "ArchiveError",
    "MigrationError",
    "PublicationLockError",
    "ReadBackMismatchError",
    "ReleaseError",
    "RetentionSafetyError",
    "StaleParentError",
    "UnknownReleaseError",
]


class ReleaseError(Exception):
    """Base for every failure the release layer raises on its own account."""


class UnknownReleaseError(ReleaseError, KeyError):
    """A release id the store does not hold.

    `KeyError` as well, because a release store is a mapping from id to manifest and a caller
    indexing it should be able to catch what indexing a mapping normally raises.
    """


class StaleParentError(ReleaseError):
    """The change set expected a parent that is no longer current (DATA-23).

    Not a retryable condition: the candidate was built against a model that has been superseded,
    so the correct response is to rebase the change set, not to publish again. Nothing has been
    written when this is raised.
    """


class PublicationLockError(ReleaseError):
    """Another writer holds the publication lock (DATA-23).

    One local writer is the contract. This names the holder — pid and when it started — because
    the only useful thing a person can do about a lock is find out whose it is.
    """


class ReadBackMismatchError(ReleaseError):
    """A staged table did not read back as what was written (DATA-23, step five).

    The whole reason the protocol reads back before publishing. Raised before the manifest exists,
    so the staged versions become orphans and the current pointer never moves.
    """


class RetentionSafetyError(ReleaseError):
    """A maintenance operation would have destroyed a version a retained manifest needs.

    DATA-58. `releases/retention.py` computes the protected set from the manifests themselves, so
    reaching this means the computation and the requested operation disagree — which is a bug in
    the caller, not a policy question.
    """


class MigrationError(ReleaseError):
    """A schema migration could not be applied, or was applied to the wrong schema version."""


class ArchiveError(ReleaseError):
    """A milestone archive could not be written completely.

    A partial archive is worse than none: DATA-25 asks for a *self-contained* export, and half of
    one still looks like a bundle.
    """
