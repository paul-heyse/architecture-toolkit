"""Round-trip source editing driven by typed commands (CORE-20).

`ARCH-TOOL-CORE-001` §5F: locate the record and field, map through the SourceMap, edit the
round-trip node, preserve comments and style, serialize, reparse, fully revalidate, present a
semantic diff. Text substitution is not the mutation method, and neither is a mutable domain
record: the presentation tree is edited and everything downstream is reparsed through the same
loader every other read uses.

Each command's edit mirrors `domain.commands.build_candidate` exactly, which is what makes the
CORE-20 property hold: the digest of the reparsed document equals the digest of the candidate the
command engine would have built. Cross-record validation and source location happen in
`validation.authoring.edit_and_validate`, because this package cannot import `validation/`.
"""

from __future__ import annotations

from dataclasses import dataclass

from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark
from ruamel.yaml.tokens import CommentToken

from architecture_toolkit.domain.authoring.loader import parse_model, parse_source
from architecture_toolkit.domain.authoring.profile import dump_text, make_yaml
from architecture_toolkit.domain.authoring.render import render_record, scalar
from architecture_toolkit.domain.commands import (
    AddElement,
    AddRelationship,
    ChangeSet,
    CommandError,
    RemoveRelationship,
    RenameElement,
    RetireElement,
    UpdateDetail,
    UpdateElement,
)
from architecture_toolkit.domain.identifiers import SemanticDigest
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import SemanticDelta, model_digest, semantic_delta
from architecture_toolkit.domain.source import SourceMap
from architecture_toolkit.domain.status import LifecycleState

__all__ = ["SourceEditError", "SourceEditResult", "apply_change_set_to_source"]


class SourceEditError(CommandError):
    """A command could not be applied to this source. Same family as `CommandError`."""


@dataclass(frozen=True, slots=True)
class SourceEditResult:
    """The edited text, reparsed and record-validated, with the delta from the baseline."""

    text: str
    model: Model
    source_map: SourceMap
    base_digest: SemanticDigest
    candidate_digest: SemanticDigest
    delta: SemanticDelta


def _presentation(text: str) -> CommentedMap:
    yaml = make_yaml()
    node = yaml.compose(text)
    tree = yaml.constructor.construct_document(node)
    if not isinstance(tree, CommentedMap):  # pragma: no cover - the loader already rejected it
        raise SourceEditError("the document root is not a mapping")
    return tree


def _find(
    tree: CommentedMap, key: str, identity_field: str, identity: str
) -> tuple[CommentedSeq, int, CommentedMap]:
    """Locate a record in the live tree by its identity.

    The tree, not the SourceMap, is searched: earlier commands in the same change set may have
    appended or removed items, and the map describes the text as it was loaded.
    """
    sequence = tree.get(key)
    if isinstance(sequence, CommentedSeq):
        for index, item in enumerate(sequence):
            if isinstance(item, CommentedMap) and item.get(identity_field) == identity:
                return sequence, index, item
    raise SourceEditError(f"{key[:-1]} {identity!r} does not exist in the source")


def _last_comment_token(node: object) -> CommentToken | None:
    """The comment token that trails a node's last scalar — where the next item's header lives."""
    if isinstance(node, CommentedSeq):
        if not node:
            return None
        slot = node.ca.items.get(len(node) - 1)
        if slot and slot[0] is not None:
            return slot[0]
        return _last_comment_token(node[-1])
    if isinstance(node, CommentedMap):
        if not node:
            return None
        last_key = list(node.keys())[-1]
        slot = node.ca.items.get(last_key)
        if slot and slot[2] is not None:
            return slot[2]
        return _last_comment_token(node[last_key])
    return None


def _attach_trailing(node: object, lines: str) -> bool:
    """Append comment lines after a node's last scalar. True if there was somewhere to put them."""
    token = _last_comment_token(node)
    if token is not None:
        token.value = token.value.rstrip("\n") + "\n" + lines
        return True
    if isinstance(node, CommentedMap) and node:
        last_key = list(node.keys())[-1]
        if isinstance(node[last_key], CommentedMap | CommentedSeq):
            return _attach_trailing(node[last_key], lines)
        node.ca.items[last_key] = [None, None, CommentToken("\n" + lines, CommentMark(0)), None]
        return True
    return False


def _trailing_token(sequence: CommentedSeq, index: int) -> CommentToken | None:
    """An item's trailing comment: the sequence slot for flow items, the last key for block ones."""
    slot = sequence.ca.items.get(index)
    if slot and slot[0] is not None:
        return slot[0]
    return _last_comment_token(sequence[index])


def _remove_item(sequence: CommentedSeq, index: int, *, parent: CommentedMap, key: str) -> None:
    """Delete one item and keep the comment block that visually belongs to the next one.

    ruamel keeps the comment lines above item *i+1* inside the trailing comment token of item
    *i*, so deleting item *i* silently drops them. The token is split at its first newline: the
    head is the removed record's own end-of-line comment and goes with it; the tail is reattached
    to the previous item's trailing token, or to the parent key's leading-comment slot when the
    first item goes.
    """
    token = _trailing_token(sequence, index)
    tail = ""
    if token is not None and "\n" in token.value:
        tail = token.value.split("\n", 1)[1]
    del sequence[index]
    if not tail.strip():
        return
    if index > 0:
        previous = _trailing_token(sequence, index - 1)
        if previous is not None:
            previous.value = previous.value.rstrip("\n") + "\n" + tail
            return
        item = sequence[index - 1]
        if isinstance(item, CommentedMap) and not item.fa.flow_style():
            if _attach_trailing(item, tail):
                return
        sequence.ca.items[index - 1] = [CommentToken("\n" + tail, CommentMark(0)), None, None, None]
        return
    slot = parent.ca.items.setdefault(key, [None, None, None, None])
    leading = slot[3] if isinstance(slot[3], list) else []
    leading.append(CommentToken(tail, CommentMark(0)))
    slot[3] = leading


def _matches_flow_style(sequence: CommentedSeq) -> bool:
    return bool(sequence) and all(
        isinstance(item, CommentedMap) and item.fa.flow_style() for item in sequence
    )


def _append(tree: CommentedMap, key: str, rendered: CommentedMap) -> None:
    sequence = tree.get(key)
    if not isinstance(sequence, CommentedSeq):
        sequence = CommentedSeq()
        tree[key] = sequence
    if _matches_flow_style(sequence):
        rendered.fa.set_flow_style()
    sequence.append(rendered)


def apply_change_set_to_source(
    text: str, change_set: ChangeSet, *, source_id: str
) -> SourceEditResult:
    """Apply typed commands to authoring text; reparse and record-validate the result."""
    loaded = parse_source(text, source_id=source_id)
    baseline = parse_model(loaded)
    if change_set.model_id != baseline.model_id:
        raise SourceEditError(
            f"change set targets {change_set.model_id!r} but the source is {baseline.model_id!r}"
        )
    base_digest = model_digest(baseline)
    if change_set.expected_base_digest is not None and change_set.expected_base_digest != (
        base_digest
    ):
        expected = change_set.expected_base_digest
        raise SourceEditError(f"the source digest is {base_digest}, not the expected {expected}")
    tree = _presentation(text)
    elements = {element.element_id for element in baseline.elements}
    relationships = {relation.relationship_id for relation in baseline.relationships}

    for command in change_set.commands:
        match command:
            case AddElement():
                if command.element.element_id in elements:
                    raise SourceEditError(f"element {command.element.element_id!r} already exists")
                elements.add(command.element.element_id)
                _append(tree, "elements", render_record(command.element))
            case UpdateElement():
                _, _, record = _find(tree, "elements", "element_id", command.element_id)
                for name, value in (
                    ("name", command.name),
                    ("description", command.description),
                    ("aliases", command.aliases),
                ):
                    if value is None:
                        continue
                    if isinstance(value, tuple):
                        aliases = CommentedSeq([scalar(alias) for alias in value])
                        aliases.fa.set_flow_style()
                        record[name] = aliases
                    else:
                        record[name] = scalar(value)
            case RenameElement():
                _, _, record = _find(tree, "elements", "element_id", command.element_id)
                current = record.get("name")
                if command.expected_name is not None and current != command.expected_name:
                    raise SourceEditError(
                        f"element {command.element_id!r} is named {current!r}, not "
                        f"{command.expected_name!r}"
                    )
                record["name"] = scalar(command.new_name)
            case RetireElement():
                _, _, record = _find(tree, "elements", "element_id", command.element_id)
                record["lifecycle_state"] = LifecycleState.RETIRED.value
            case AddRelationship():
                identity = command.relationship.relationship_id
                if identity in relationships:
                    raise SourceEditError(f"relationship {identity!r} already exists")
                relationships.add(identity)
                _append(tree, "relationships", render_record(command.relationship))
            case RemoveRelationship():
                sequence, index, _ = _find(
                    tree, "relationships", "relationship_id", command.relationship_id
                )
                relationships.discard(command.relationship_id)
                _remove_item(sequence, index, parent=tree, key="relationships")
            case UpdateDetail():
                _, _, record = _find(tree, "elements", "element_id", command.element_id)
                if command.detail is None:
                    record.pop("detail", None)
                    continue
                rendered = render_record(command.detail)
                existing = record.get("detail")
                same_family = isinstance(existing, CommentedMap) and existing.get(
                    "detail_family"
                ) == rendered.get("detail_family")
                if same_family and isinstance(existing, CommentedMap):
                    for stale in [key for key in existing if key not in rendered]:
                        del existing[stale]
                    for name, value in rendered.items():
                        existing[name] = value
                else:
                    record["detail"] = rendered
    new_text = dump_text(tree)
    reparsed = parse_source(new_text, source_id=source_id)
    model = parse_model(reparsed)
    return SourceEditResult(
        text=new_text,
        model=model,
        source_map=reparsed.source_map,
        base_digest=base_digest,
        candidate_digest=model_digest(model),
        delta=semantic_delta(baseline, model),
    )
