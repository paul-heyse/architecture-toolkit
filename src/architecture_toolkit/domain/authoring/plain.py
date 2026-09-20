"""Plain data and the SourceMap from one node-tree walk (CORE-17, CORE-18).

The walk is over the *composed* node tree, not the constructed round-trip tree, for two reasons.
Nodes carry an end mark as well as a start mark, including scalars inside flow collections, so
the SourceMap gets full extents. And scalar meaning is decided here by resolved tag rather than
by whatever Python type ruamel would construct: under the round-trip loader a plain `2024-01-01`
constructs as `datetime.date` and `0x1F` as a `HexCapsInt`, and neither is authoring data the
domain should ever see. The core schema's seven tags are the whole vocabulary; a plain timestamp
is a string; anything else was rejected by the pre-pass.

CORE-17 in practice: what leaves this module is `str`, `int`, `float`, `bool`, `None`, `tuple`
and `dict`, exactly, and `tests/unit/test_source_map.py` checks the types by identity so a
`ScalarString` cannot slip through as a `str`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ruamel.yaml.constructor import RoundTripConstructor
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from architecture_toolkit.domain.authoring.errors import AuthoringError
from architecture_toolkit.domain.source import SourceEntry, SourceLocation, render_segments

__all__ = ["IDENTITY_KEYS", "Plain", "WalkResult", "build_plain"]

type Plain = str | int | float | bool | tuple[Plain, ...] | dict[str, Plain] | None

# The keys that name a sequence item's identity, checked in this order. A mapping item under a
# sequence that carries one gets an identity-grammar path so a cross-record diagnostic addressed
# by ID resolves to it. Participants are keyed by the element they name.
IDENTITY_KEYS: Final[tuple[str, ...]] = (
    "element_id",
    "relationship_id",
    "interaction_id",
    "reference_id",
    "link_id",
    "binding_id",
    "field_id",
    "node_id",
    "transition_id",
)

_TAG = "tag:yaml.org,2002:"
_STR, _INT, _FLOAT, _BOOL, _NULL = (f"{_TAG}{n}" for n in ("str", "int", "float", "bool", "null"))
_TIMESTAMP = f"{_TAG}timestamp"


class _Walk:
    def __init__(self, constructor: RoundTripConstructor, source_id: str) -> None:
        self.constructor = constructor
        self.source_id = source_id
        self.entries: dict[str, SourceEntry] = {}
        self.identity_paths: dict[str, str] = {}
        self.record_paths: dict[str, list[str]] = {}

    def location(self, node: Node, path: str) -> SourceLocation:
        return SourceLocation(
            source_id=self.source_id,
            semantic_path=path,
            line=node.start_mark.line + 1,
            column=node.start_mark.column + 1,
            end_line=node.end_mark.line + 1,
            end_column=max(node.end_mark.column, 1),
        )

    def scalar(self, node: ScalarNode) -> Plain:
        tag = str(node.tag)
        if tag == _STR or tag == _TIMESTAMP:
            return str(node.value)
        if tag == _NULL:
            return None
        if tag == _BOOL:
            return bool(self.constructor.construct_object(node))
        if tag == _INT:
            return int(self.constructor.construct_object(node))
        if tag == _FLOAT:
            return float(self.constructor.construct_object(node))
        # Unreachable after the pre-pass, which rejects every explicit non-core tag. Raising
        # rather than coercing keeps a future ruamel resolver change from silently widening the
        # authoring vocabulary.
        raise RuntimeError(f"unexpected scalar tag {tag!r} at {node.start_mark}")

    def visit(
        self,
        node: Node,
        segments: tuple[str | int, ...],
        identity: tuple[str, ...] | None,
        key_node: Node | None,
    ) -> Plain:
        path = render_segments(segments)
        identity_path = None if identity is None else ".".join(identity)
        entry = SourceEntry(
            path=path,
            segments=segments,
            value=self.location(node, path),
            key=None if key_node is None else self.location(key_node, path),
            identity_path=identity_path,
        )
        self.entries[path] = entry
        if identity_path is not None:
            self.identity_paths.setdefault(identity_path, path)

        if isinstance(node, MappingNode):
            result: dict[str, Plain] = {}
            for key, value in node.value:
                if not isinstance(key, ScalarNode):
                    raise AuthoringError(
                        "CORE.YAML.SYNTAX",
                        "complex mapping keys are not supported by the authoring profile",
                        location=self.location(key, path),
                    )
                name = str(key.value)
                child_identity = None if identity is None else (*identity, name)
                result[name] = self.visit(value, (*segments, name), child_identity, key)
            return result
        if isinstance(node, SequenceNode):
            items: list[Plain] = []
            for index, item in enumerate(node.value):
                item_identity = self._item_identity(item, identity if identity else segments)
                if item_identity is None and identity is not None:
                    item_identity = (*identity, str(index))
                items.append(self.visit(item, (*segments, index), item_identity, None))
            return tuple(items)
        if isinstance(node, ScalarNode):
            return self.scalar(node)
        raise RuntimeError(f"unknown node type {type(node).__name__}")  # pragma: no cover

    def _item_identity(
        self, item: Node, prefix: tuple[str | int, ...] | tuple[str, ...]
    ) -> tuple[str, ...] | None:
        """`elements[3]` becomes `elements.schema-1` when the item declares an identity key."""
        if not isinstance(item, MappingNode):
            return None
        for key, value in item.value:
            if (
                isinstance(key, ScalarNode)
                and str(key.value) in IDENTITY_KEYS
                and isinstance(value, ScalarNode)
                and str(value.tag) == _STR
            ):
                identity = str(value.value)
                spelled = (*(str(segment) for segment in prefix), identity)
                # Only a top-level collection item is a record; a participant or a schema
                # field also carries an identity key, but a diagnostic addressed at that
                # identity means the record, not the mention.
                if len(prefix) == 1:
                    self.record_paths.setdefault(identity, []).append(".".join(spelled))
                return spelled
        return None


@dataclass(frozen=True, slots=True)
class WalkResult:
    """What one walk of a composed document yields."""

    data: dict[str, Plain]
    entries: dict[str, SourceEntry]
    identity_paths: dict[str, str]
    record_paths: dict[str, tuple[str, ...]]


def build_plain(node: Node, *, source_id: str, constructor: RoundTripConstructor) -> WalkResult:
    """Walk a composed document: plain data, entries by path, identity paths, record paths.

    The root must be a mapping; anything else is `CORE.YAML.NOT_A_MAPPING` at the root.
    """
    if not isinstance(node, MappingNode):
        raise AuthoringError(
            "CORE.YAML.NOT_A_MAPPING",
            "the document root must be a mapping of model fields",
            location=SourceLocation(
                source_id=source_id,
                semantic_path="",
                line=node.start_mark.line + 1,
                column=node.start_mark.column + 1,
            ),
        )
    walk = _Walk(constructor, source_id)
    data = walk.visit(node, (), None, None)
    if not isinstance(data, dict):  # pragma: no cover - a MappingNode always yields a dict
        raise RuntimeError("the root walk did not produce a mapping")
    return WalkResult(
        data=data,
        entries=walk.entries,
        identity_paths=walk.identity_paths,
        record_paths={key: tuple(paths) for key, paths in walk.record_paths.items()},
    )
