"""Typed authoring failures (CORE-15, CORE-16).

`domain/` cannot import `validation/`, so the adapter cannot build a `Diagnostic`. It raises this
instead, carrying a registered code, a location and bounded context, and
`validation.normalize.normalize_authoring_error` maps it — the same shape as the Pydantic
`ValidationError` bridge. `AUTHORING_CODES` is the adapter's side of the registry;
`tests/unit/test_authoring_codes.py` asserts it equals the `CORE.YAML.*` area of
`validation/codes.py`, which keeps the two aligned without a runtime import.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

from architecture_toolkit.domain.source import SourceLocation

__all__ = ["AUTHORING_CODES", "AuthoringError"]

AUTHORING_CODES: Final[frozenset[str]] = frozenset(
    {
        "CORE.YAML.DUPLICATE_KEY",
        "CORE.YAML.ANCHOR",
        "CORE.YAML.ALIAS",
        "CORE.YAML.MERGE_KEY",
        "CORE.YAML.CUSTOM_TAG",
        "CORE.YAML.PYTHON_TAG",
        "CORE.YAML.UNSUPPORTED_VERSION",
        "CORE.YAML.DEPTH_EXCEEDED",
        "CORE.YAML.MULTIPLE_DOCUMENTS",
        "CORE.YAML.SYNTAX",
        "CORE.YAML.NOT_A_MAPPING",
    }
)


class AuthoringError(ValueError):
    """One authoring violation, with any further violations from the same pass in `related`.

    Every finding in a document is reported rather than the first only, so an author fixes a
    file in one round. The first is raised; the rest ride along in stream order.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        location: SourceLocation,
        context: tuple[tuple[str, str], ...] = (),
        related: tuple[AuthoringError, ...] = (),
    ) -> None:
        if code not in AUTHORING_CODES:
            raise ValueError(f"{code!r} is not an authoring code")
        super().__init__(message)
        self.code: str = code
        self.message: str = message
        self.location: SourceLocation = location
        self.context: tuple[tuple[str, str], ...] = tuple(sorted(context))
        self.related: tuple[AuthoringError, ...] = related

    def __iter__(self) -> Iterator[AuthoringError]:
        """Itself first, then every related finding, in stream order."""
        yield self
        yield from self.related
