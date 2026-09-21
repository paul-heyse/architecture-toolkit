"""Refusals from the change layer.

Separate from `queries/errors.py` and `releases/errors.py` rather than reusing either, because a
caller that wants to distinguish "this release does not exist" from "this pair is not a revision"
can only do that if the two are different types. None of these is a `Diagnostic`: a diagnostic is a
finding *about a model*, and these are refusals to answer a question at all.
"""

__all__ = [
    "ChangeError",
    "ClassificationError",
    "DiffError",
    "LineageError",
    "ReviewError",
]


class ChangeError(Exception):
    """Anything the change layer refuses."""


class ClassificationError(ChangeError):
    """The classification table does not describe the model it is asked about."""


class DiffError(ChangeError):
    """Two models or releases cannot be compared as asked."""


class LineageError(DiffError):
    """The two releases are not related the way the caller assumed (DATA-28)."""


class ReviewError(ChangeError):
    """A change set was asked to advance without the review it requires."""
