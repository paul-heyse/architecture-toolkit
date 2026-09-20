"""Source locations and the SourceMap (CORE-18, CORE-19).

`SourceLocation` moved here from `validation/diagnostics.py`, unchanged, because the authoring
adapter in `domain/authoring/` produces locations and `domain/` cannot import `validation/`.
`validation.diagnostics` re-exports it, so the class name, the import path a caller uses and the
generated JSON Schema (`$defs.SourceLocation`) are all identical to W1's.

**One path grammar.** `render_segments` turns a Pydantic-style location tuple into the semantic
path used everywhere: `elements[7].detail.fields[1].references_element_id`. The SourceMap is keyed
by it, `validation.normalize.field_path` renders through it, and the diagnostic renderer prints
it. A second, identity-keyed grammar — `elements.schema-1.detail.fields.submitted_by` — is what
W1's cross-record rules emit in `field_path`; the SourceMap indexes both, generated from one walk,
so a rule diagnostic resolves without any rule changing what it says.

The SourceMap is build metadata (`ARCH-TOOL-CORE-001` §5D). It is a frozen dataclass over
read-only mappings rather than a Pydantic record, it is never persisted, and no schema family
names it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field

from architecture_toolkit.domain.base import CompiledRecord

__all__ = [
    "LocationResolution",
    "SourceEntry",
    "SourceLocation",
    "SourceMap",
    "render_segments",
    "split_path",
]


class SourceLocation(CompiledRecord):
    """Where in the authored source a diagnostic came from. Populated at W2 (CORE-18)."""

    # All positions are 1-based; ruamel's 0-based marks are converted by the adapter. The
    # docstring is the schema description and is kept exactly as W1 published it.

    source_id: str = Field(min_length=1)
    document_id: str | None = None
    semantic_path: str | None = None
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    end_column: int | None = Field(default=None, ge=1)


class LocationResolution(StrEnum):
    """How a diagnostic's location was found, stated so a fallback is never mistaken for a hit.

    `ARCH-TOOL-CORE-001` §5E orders the chain: exact canonical ID and field path, then the
    semantic path, then the nearest parent record, then the document.
    """

    EXACT = "exact"
    PATH = "path"
    PARENT = "parent"
    DOCUMENT = "document"


def render_segments(segments: Sequence[str | int]) -> str:
    """`("elements", 7, "detail")` -> `elements[7].detail`; the empty tuple renders as `""`."""
    parts: list[str] = []
    for segment in segments:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        else:
            parts.append(f".{segment}" if parts else segment)
    return "".join(parts).lstrip(".")


def split_path(path: str) -> tuple[str | int, ...]:
    """The inverse of `render_segments` for the semantic grammar.

    Only the semantic grammar is parsed here: its keys are field names, which never contain a
    dot. The identity grammar is *not* split, because identifiers may contain dots
    (`software.system.billing`) and tokenizing one would corrupt it; `validation/locate.py`
    resolves identity paths by lookup and suffix matching instead.
    """
    segments: list[str | int] = []
    token = ""
    digits = ""
    in_index = False
    for character in path:
        if in_index:
            if character == "]":
                segments.append(int(digits))
                digits = ""
                in_index = False
            else:
                digits += character
            continue
        if character == "[":
            if token:
                segments.append(token)
                token = ""
            in_index = True
            continue
        if character == ".":
            if token:
                segments.append(token)
                token = ""
            continue
        token += character
    if token:
        segments.append(token)
    return tuple(segments)


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """One node of the authored document and where it is.

    `value` spans the node; `key` is the position of the mapping key that introduces it, present
    for mapping values so an unknown-field diagnostic can point at the key the author typed.
    `identity_path` is the identity-grammar spelling when this node sits under an identity-keyed
    sequence item.
    """

    path: str
    segments: tuple[str | int, ...]
    value: SourceLocation
    key: SourceLocation | None = None
    identity_path: str | None = None


@dataclass(frozen=True, slots=True)
class SourceMap:
    """Semantic path -> location, built before Pydantic conversion (CORE-18).

    `entries` is keyed by the semantic grammar; `identity_paths` maps the identity grammar onto
    it; `record_paths` maps a bare identity to every identity-grammar path it introduces (more
    than one only when a document repeats an identity, which the identity rule reports).
    """

    source_id: str
    document_id: str | None
    source_digest: str
    parser_version: str
    profile_version: str
    root: SourceLocation
    entries: Mapping[str, SourceEntry]
    identity_paths: Mapping[str, str]
    record_paths: Mapping[str, tuple[str, ...]]

    def lookup(self, path: str) -> SourceEntry | None:
        return self.entries.get(path)

    def lookup_identity(self, identity_path: str) -> SourceEntry | None:
        semantic = self.identity_paths.get(identity_path)
        return None if semantic is None else self.entries.get(semantic)

    def nearest(self, segments: Sequence[str | int]) -> tuple[SourceEntry | None, int]:
        """The longest prefix of `segments` that is mapped, and how many segments matched.

        Zero matched means the document root; the root entry is always present.
        """
        for count in range(len(segments), -1, -1):
            entry = self.entries.get(render_segments(segments[:count]))
            if entry is not None:
                return entry, count
        return None, 0
