"""Render validated records into presentation nodes (CORE-20).

A new record enters a document as a `CommentedMap` built from its JSON-mode dump, so what is
written is exactly what would validate back. Two adjustments are needed and both are
principled rather than cosmetic. Discriminators are `Literal` fields with defaults, which
`exclude_defaults=True` drops; without them the reparsed union cannot be resolved, so they are
re-inserted from the annotations. And scalar-only sequences are written in flow style — the
example fixture's convention for `aliases`, `key_membership` and the like — while records stay in
block style so their comments have somewhere to live.

`content_hash` is never rendered: it is derived, and a stored digest in authoring source would
be a claim the author did not make.
"""

from __future__ import annotations

import json
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from architecture_toolkit.domain.authoring.profile import dump_text

__all__ = ["render_model_text", "render_record", "scalar"]

_NEVER_RENDERED = frozenset({"content_hash"})

# Two ruamel round-trip asymmetries, both found by the CORE-20 property rather than by reading
# the specification. The emitter still treats U+0085 (NEL) as a YAML 1.1 line break, so written
# plain it comes back as a space; and a plain scalar beginning with `?` inside a flow sequence is
# emitted as `[?x]` and read back as a complex key. Double-quoted style is the representation
# that survives both. Every other code point probed, control characters included, round-trips.
_NEEDS_ESCAPING = ("\x85",)
_UNSAFE_FIRST = "?"


def scalar(value: str) -> str:
    """A string value in the style that survives a dump and a reload."""
    if value.startswith(_UNSAFE_FIRST) or any(character in value for character in _NEEDS_ESCAPING):
        return DoubleQuotedScalarString(value)
    return value


def _is_literal(annotation: object) -> bool:
    if get_origin(annotation) is Literal:
        return True
    return any(_is_literal(argument) for argument in get_args(annotation))


def _render(value: object, full: Any, sparse: Any) -> Any:
    """Walk the instance with its full and sparse dumps; return presentation nodes."""
    if isinstance(value, BaseModel):
        node = CommentedMap()
        for name, field in type(value).model_fields.items():
            if name in _NEVER_RENDERED:
                continue
            present = isinstance(sparse, dict) and name in sparse
            if not present and not _is_literal(field.annotation):
                continue
            inner = getattr(value, name)
            inner_full = full[name] if isinstance(full, dict) else None
            inner_sparse = sparse[name] if present and isinstance(sparse, dict) else None
            node[name] = _render(inner, inner_full, inner_sparse if present else inner_full)
        return node
    if isinstance(value, frozenset):
        node = CommentedSeq(sorted(full, key=json.dumps))
        node.fa.set_flow_style()
        return node
    if isinstance(value, tuple):
        items = [
            _render(inner, inner_full, inner_sparse)
            for inner, inner_full, inner_sparse in zip(value, full, sparse, strict=True)
        ]
        node = CommentedSeq(items)
        if all(not isinstance(item, CommentedMap | CommentedSeq) for item in items):
            node.fa.set_flow_style()
        return node
    if isinstance(full, str):
        return scalar(full)
    return full


def render_record(record: BaseModel) -> CommentedMap:
    """A presentation mapping for one record, defaults omitted, discriminators kept."""
    full = record.model_dump(mode="json")
    sparse = record.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
    rendered = _render(record, full, sparse)
    if not isinstance(rendered, CommentedMap):  # pragma: no cover - a record renders a mapping
        raise RuntimeError("a record did not render as a mapping")
    return rendered


def render_model_text(record: BaseModel) -> str:
    """The whole model as authoring text in the profile's style."""
    return dump_text(render_record(record))
