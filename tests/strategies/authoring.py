"""Presentation-only rewrites of an authoring document (CORE-21).

`reformatted(text)` loads the text into ruamel's presentation tree, applies a drawn set of
changes that alter how the document *looks* and nothing about what it *says* — requoting,
flow/block style, inserted comments, reordered mapping keys, reordered unordered collections,
reordered ordinal-bearing lists with their ordinals kept, and different indentation and width on
output — and dumps it again. The property in `tests/property/test_authoring_properties.py`
asserts the semantic digest survives every one of them.

Every rewrite is drawn from a `boolean` or a `permutation`, never filtered, so shrinking
converges on the single rewrite that broke a digest.
"""

from __future__ import annotations

import io

from hypothesis import strategies as st
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString

from architecture_toolkit.domain.authoring.profile import make_yaml

__all__ = ["reformatted"]

UNORDERED_COLLECTIONS = (
    "elements",
    "relationships",
    "interactions",
    "references",
    "reference_links",
    "notation_bindings",
    "views",
    # DATA-13: an extension is identified by `(namespace, key)`, so the order they were written
    # in is presentation like any other unordered collection.
    "extensions",
)
# Ordered by their `ordinal`, so shuffling the items is presentation.
ORDINAL_LISTS = ("participants", "fields", "nodes", "transitions")


def _requote(draw: st.DrawFn, value: str) -> str:
    """Requote a string in a style that is a pure presentation choice for *this* string.

    Double-quoted style escapes everything and is always safe. Single-quoted style is only a
    presentation choice for printable text: ruamel wraps a single-quoted scalar at a C1 control
    character and the reload folds that break into a space — found by the property, and the
    reason the renderer never emits single quotes itself.
    """
    if "\x85" in value or "\n" in value or draw(st.booleans()):
        return value
    if not value.isprintable() or "'" in value or draw(st.booleans()):
        return DoubleQuotedScalarString(value)
    return SingleQuotedScalarString(value)


def _flow_safe(node: CommentedMap) -> bool:
    """A mapping can switch to flow style only if nothing in it needs a block."""
    return (
        all(
            isinstance(value, str | int | float | bool | type(None))
            and not (isinstance(value, str) and "\n" in value)
            for value in node.values()
        )
        and not node.ca.items
    )


def _shuffle(draw: st.DrawFn, sequence: CommentedSeq) -> None:
    if len(sequence) < 2:
        return
    order = draw(st.permutations(range(len(sequence))))
    items = [sequence[index] for index in order]
    for index, item in enumerate(items):
        sequence[index] = item


def _rewrite(draw: st.DrawFn, node: object, *, key: str | None) -> None:
    if isinstance(node, CommentedMap):
        keys = list(node.keys())
        if len(keys) > 1 and draw(st.booleans()):
            order = draw(st.permutations(keys))
            values = {name: node[name] for name in keys}
            for name in keys:
                del node[name]
            for name in order:
                node[name] = values[name]
        for name in list(node.keys()):
            value = node[name]
            if isinstance(value, str):
                node[name] = _requote(draw, value)
            elif isinstance(value, CommentedMap | CommentedSeq):
                _rewrite(draw, value, key=name)
        if _flow_safe(node) and draw(st.booleans()):
            node.fa.set_flow_style()
        elif node.fa.flow_style() and draw(st.booleans()):
            node.fa.set_block_style()
        if not node.fa.flow_style() and draw(st.booleans()):
            for name in list(node.keys()):
                if draw(st.booleans()):
                    node.yaml_set_comment_before_after_key(name, before=f"about {name}")
                if isinstance(node[name], str | int) and draw(st.booleans()):
                    node.yaml_add_eol_comment("trailing note", name)
        return
    if isinstance(node, CommentedSeq):
        if key in UNORDERED_COLLECTIONS or key in ORDINAL_LISTS:
            _shuffle(draw, node)
        for index, item in enumerate(node):
            if isinstance(item, str):
                node[index] = _requote(draw, item)
            elif isinstance(item, CommentedMap | CommentedSeq):
                _rewrite(draw, item, key=None)


@st.composite
def reformatted(draw: st.DrawFn, text: str) -> str:
    """`text` rewritten in a drawn presentation, semantically identical by construction."""
    yaml = make_yaml()
    tree = yaml.load(text)
    if not isinstance(tree, CommentedMap):
        return text
    _rewrite(draw, tree, key=None)
    if draw(st.booleans()):
        mapping, sequence, offset = draw(st.sampled_from([(4, 6, 4), (2, 2, 0), (3, 5, 3)]))
        yaml.indent(mapping=mapping, sequence=sequence, offset=offset)
    if draw(st.booleans()):
        yaml.width = draw(st.sampled_from([40, 72, 200]))
    buffer = io.StringIO()
    yaml.dump(tree, buffer)
    return buffer.getvalue()
