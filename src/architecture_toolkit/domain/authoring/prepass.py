"""The forbidden-construct pre-pass over parser events (CORE-15, CORE-16).

Why events rather than the loaded tree: the round-trip loader resolves aliases into shared
objects, folds merge keys into their mapping and constructs tagged values as `TaggedScalar`s —
by the time a tree exists, the construct is gone and its position with it. Parser events carry
every construct verbatim with exact start and end marks, so each forbidden form is reported
with its own stable code at the line and column the author wrote it.

Duplicate keys are found here too, and deliberately: neither `parse()` nor `compose()` detects
them, only construction does, and construction is exactly the step the loader skips for
mappings. Finding them in the pre-pass also yields the semantic path of the offending key.
`allow_duplicate_keys=False` on the profile remains as a backstop.

All findings are collected; the first is raised with the rest attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ruamel.yaml.error import MarkedYAMLError, YAMLError
from ruamel.yaml.events import (
    AliasEvent,
    DocumentStartEvent,
    Event,
    MappingEndEvent,
    MappingStartEvent,
    ScalarEvent,
    SequenceEndEvent,
    SequenceStartEvent,
)

from architecture_toolkit.domain.authoring.errors import AuthoringError
from architecture_toolkit.domain.authoring.profile import (
    CORE_SCHEMA_TAGS,
    MAX_DEPTH,
    PERMITTED_VERSIONS,
    PYTHON_TAG_PREFIX,
    make_yaml,
)
from architecture_toolkit.domain.source import SourceLocation, render_segments

__all__ = ["check_events"]

_MERGE_KEY = "<<"


@dataclass(slots=True)
class _Frame:
    kind: Literal["map", "seq"]
    segments: tuple[str | int, ...]
    expecting_key: bool = True
    current_key: str | None = None
    index: int = 0
    seen: set[str] = field(default_factory=set)


class _Scan:
    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        self.stack: list[_Frame] = []
        self.findings: list[AuthoringError] = []
        self.documents = 0
        self.depth_reported = False

    # -- helpers ------------------------------------------------------------------------------

    def _location(self, event: Event, segments: tuple[str | int, ...]) -> SourceLocation:
        start, end = event.start_mark, event.end_mark
        return SourceLocation(
            source_id=self.source_id,
            semantic_path=render_segments(segments),
            line=start.line + 1,
            column=start.column + 1,
            end_line=None if end is None else end.line + 1,
            end_column=None if end is None else end.column,
        )

    def _report(
        self,
        code: str,
        message: str,
        event: Event,
        segments: tuple[str | int, ...],
        **context: str,
    ) -> None:
        self.findings.append(
            AuthoringError(
                code,
                message,
                location=self._location(event, segments),
                context=tuple(context.items()),
            )
        )

    def _child_segments(self) -> tuple[str | int, ...]:
        if not self.stack:
            return ()
        frame = self.stack[-1]
        if frame.kind == "seq":
            return (*frame.segments, frame.index)
        if frame.current_key is None:
            return frame.segments
        return (*frame.segments, frame.current_key)

    def _node_completed(self) -> None:
        """A scalar, alias or closed collection finished under the current frame."""
        if not self.stack:
            return
        frame = self.stack[-1]
        if frame.kind == "seq":
            frame.index += 1
        else:
            frame.expecting_key = True
            frame.current_key = None

    def _check_tag_and_anchor(self, event: Event, segments: tuple[str | int, ...]) -> None:
        anchor = getattr(event, "anchor", None)
        if anchor:
            self._report(
                "CORE.YAML.ANCHOR",
                f"anchor &{anchor} is not permitted; repeat the value instead",
                event,
                segments,
                anchor=str(anchor),
            )
        tag = getattr(event, "tag", None)
        if tag is None:
            return
        name = str(tag)
        if name.startswith(PYTHON_TAG_PREFIX):
            self._report(
                "CORE.YAML.PYTHON_TAG",
                f"tag {name} names a Python constructor; unsafe tags are not permitted",
                event,
                segments,
                tag=name,
            )
        elif name not in CORE_SCHEMA_TAGS:
            self._report(
                "CORE.YAML.CUSTOM_TAG",
                f"tag {name} is outside the YAML 1.2 core schema the authoring profile permits",
                event,
                segments,
                tag=name,
            )

    # -- events --------------------------------------------------------------------------------

    def document_start(self, event: DocumentStartEvent) -> None:
        self.documents += 1
        if self.documents > 1:
            self._report(
                "CORE.YAML.MULTIPLE_DOCUMENTS",
                "a source file holds exactly one document",
                event,
                (),
                document=str(self.documents),
            )
        version = event.version
        if version is not None and tuple(version) not in PERMITTED_VERSIONS:
            self._report(
                "CORE.YAML.UNSUPPORTED_VERSION",
                f"%YAML {version[0]}.{version[1]} is not supported; the profile is YAML 1.2",
                event,
                (),
                version=f"{version[0]}.{version[1]}",
            )

    def key_scalar(self, event: ScalarEvent, frame: _Frame) -> None:
        key = str(event.value)
        segments = (*frame.segments, key)
        if event.style is None and event.tag is None and key == _MERGE_KEY:
            self._report(
                "CORE.YAML.MERGE_KEY",
                "merge keys are not permitted; write the merged keys out",
                event,
                segments,
            )
        elif key in frame.seen:
            self._report(
                "CORE.YAML.DUPLICATE_KEY",
                f"key {key!r} appears more than once in this mapping",
                event,
                segments,
                key=key,
            )
        frame.seen.add(key)
        frame.current_key = key
        frame.expecting_key = False

    def node(self, event: Event) -> None:
        """A scalar, alias, mapping start or sequence start in node position."""
        frame = self.stack[-1] if self.stack else None
        if frame is not None and frame.kind == "map" and frame.expecting_key:
            if isinstance(event, ScalarEvent):
                self._check_tag_and_anchor(event, (*frame.segments, str(event.value)))
                self.key_scalar(event, frame)
                return
            # A collection or alias in key position. YAML allows it; the authoring subset
            # (mappings, sequences, scalars) does not.
            frame.current_key = None
            frame.expecting_key = False
            if isinstance(event, AliasEvent):
                self._report(
                    "CORE.YAML.ALIAS",
                    f"alias *{event.anchor} is not permitted; repeat the value instead",
                    event,
                    frame.segments,
                    anchor=str(event.anchor),
                )
                return
            self._report(
                "CORE.YAML.SYNTAX",
                "complex mapping keys are not supported by the authoring profile",
                event,
                frame.segments,
            )
            self._push(event, frame.segments)
            return

        segments = self._child_segments()
        if isinstance(event, AliasEvent):
            self._report(
                "CORE.YAML.ALIAS",
                f"alias *{event.anchor} is not permitted; repeat the value instead",
                event,
                segments,
                anchor=str(event.anchor),
            )
            self._node_completed()
            return
        self._check_tag_and_anchor(event, segments)
        if isinstance(event, ScalarEvent):
            self._node_completed()
            return
        self._push(event, segments)

    def _push(self, event: Event, segments: tuple[str | int, ...]) -> None:
        kind: Literal["map", "seq"] = "map" if isinstance(event, MappingStartEvent) else "seq"
        self.stack.append(_Frame(kind=kind, segments=segments))
        if len(self.stack) > MAX_DEPTH and not self.depth_reported:
            self.depth_reported = True
            self._report(
                "CORE.YAML.DEPTH_EXCEEDED",
                f"nesting deeper than {MAX_DEPTH} collections is not permitted",
                event,
                segments,
                depth=str(len(self.stack)),
                max_depth=str(MAX_DEPTH),
            )

    def end(self) -> None:
        if self.stack:
            self.stack.pop()
        self._node_completed()


def check_events(text: str, *, source_id: str) -> None:
    """Raise `AuthoringError` for every forbidden construct in `text`, or return silently."""
    scan = _Scan(source_id)
    try:
        for event in make_yaml().parse(text):
            if isinstance(event, DocumentStartEvent):
                scan.document_start(event)
            elif isinstance(
                event, ScalarEvent | AliasEvent | MappingStartEvent | SequenceStartEvent
            ):
                scan.node(event)
            elif isinstance(event, MappingEndEvent | SequenceEndEvent):
                scan.end()
    except MarkedYAMLError as failure:
        mark = failure.problem_mark
        scan.findings.append(
            AuthoringError(
                "CORE.YAML.SYNTAX",
                str(failure.problem or failure.context or "the document is not well-formed YAML"),
                location=SourceLocation(
                    source_id=source_id,
                    semantic_path=render_segments(scan._child_segments()),
                    line=None if mark is None else mark.line + 1,
                    column=None if mark is None else mark.column + 1,
                ),
            )
        )
    except YAMLError as failure:
        scan.findings.append(
            AuthoringError(
                "CORE.YAML.SYNTAX",
                str(failure).splitlines()[0] if str(failure) else "the source could not be read",
                location=SourceLocation(source_id=source_id, semantic_path="", line=1, column=1),
            )
        )
    if scan.findings:
        first, *rest = scan.findings
        raise AuthoringError(
            first.code,
            first.message,
            location=first.location,
            context=first.context,
            related=tuple(rest),
        )
