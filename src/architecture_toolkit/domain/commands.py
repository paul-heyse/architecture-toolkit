"""Typed change commands (CORE-04, CORE-09, CORE-10).

core.md's mutation pipeline is `validated baseline + typed ChangeCommand(s) -> candidate
construction -> complete Pydantic validation -> cross-record validation -> immutable candidate`.
This module owns the first two steps. `validation/pipeline.py` composes the rest, which is what
keeps the domain from importing the rules that judge it.

**No bypass, and the reason is concrete.** `model_copy(update=...)` on a strict frozen record
was measured producing both a `name=''` that violates `min_length` and an `element_id=123` that
is not even a string. It does not validate, at all. Rebuilding through `model_validate` costs a
revalidation and is the only way the result is a record rather than a shape. `no-validation-bypass`
enforces this structurally.

**`RenameElement` is deliberately narrower than `UpdateElement`.** They could be one command,
and then a rename would be indistinguishable from any other field edit — W6's semantic diff
would classify it as an anonymous update, and the M1 gate "rename preserves identity" would have
nothing to assert about. Retyping an element (`kind_id`) is intentionally *not* expressible: it
changes permitted endpoints and permitted detail families, so it is a retire plus an add at the
semantic level and pretending otherwise would let a model silently change meaning.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from architecture_toolkit.domain.base import CommandRecord
from architecture_toolkit.domain.details import ElementDetail
from architecture_toolkit.domain.identifiers import (
    ChangeSetId,
    ElementId,
    ModelId,
    RelationshipId,
    SemanticDigest,
)
from architecture_toolkit.domain.model import Element, Model, Relationship
from architecture_toolkit.domain.status import LifecycleState

__all__ = [
    "CHANGE_SET_ADAPTER",
    "COMMAND_BATCH_ADAPTER",
    "AddElement",
    "AddRelationship",
    "ChangeCommand",
    "ChangeSet",
    "CommandError",
    "RemoveRelationship",
    "RenameElement",
    "RetireElement",
    "UpdateDetail",
    "UpdateElement",
    "build_candidate",
]


class CommandError(ValueError):
    """A command could not be applied to this baseline. Not a model-content problem."""


class AddElement(CommandRecord):
    command: Literal["add_element"] = "add_element"
    element: Element


class UpdateElement(CommandRecord):
    """Descriptive fields only. Identity, kind and status are changed by other means."""

    command: Literal["update_element"] = "update_element"
    element_id: ElementId
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    aliases: tuple[str, ...] | None = None


class RenameElement(CommandRecord):
    """Change the display name and nothing else.

    `expected_name` is optimistic concurrency at the field: an author renaming what they believe
    is "Review request" should fail rather than overwrite a rename someone else already made.
    """

    command: Literal["rename_element"] = "rename_element"
    element_id: ElementId
    new_name: str = Field(min_length=1)
    expected_name: str | None = None


class RetireElement(CommandRecord):
    command: Literal["retire_element"] = "retire_element"
    element_id: ElementId
    reason: str | None = None


class AddRelationship(CommandRecord):
    command: Literal["add_relationship"] = "add_relationship"
    relationship: Relationship


class RemoveRelationship(CommandRecord):
    command: Literal["remove_relationship"] = "remove_relationship"
    relationship_id: RelationshipId


class UpdateDetail(CommandRecord):
    command: Literal["update_detail"] = "update_detail"
    element_id: ElementId
    detail: ElementDetail | None = None


ChangeCommand = Annotated[
    AddElement
    | UpdateElement
    | RenameElement
    | RetireElement
    | AddRelationship
    | RemoveRelationship
    | UpdateDetail,
    Field(discriminator="command"),
]

COMMAND_BATCH_ADAPTER: TypeAdapter[tuple[ChangeCommand, ...]] = TypeAdapter(
    tuple[ChangeCommand, ...]
)
"""CORE-05: a natural collection boundary, not a wrapper model created to call validation."""


class ChangeSet(CommandRecord):
    change_set_id: ChangeSetId
    model_id: ModelId
    # The batch-level stale-parent check. DATA-23 requires a publication against a stale expected
    # parent to fail, and putting it here rather than per command means it fails once, before
    # anything is applied, rather than halfway through.
    expected_base_digest: SemanticDigest | None = None
    commands: tuple[ChangeCommand, ...]

    @model_validator(mode="after")
    def at_least_one_command(self) -> Self:
        if not self.commands:
            message = f"change set {self.change_set_id!r} contains no commands"
            raise ValueError(message)
        return self


CHANGE_SET_ADAPTER: TypeAdapter[ChangeSet] = TypeAdapter(ChangeSet)


def _revalidate(record: Element, **changes: object) -> Element:
    """Rebuild through full validation. The only sanctioned way to change a frozen record.

    `dict(record)` keeps nested records as instances rather than round-tripping them through
    dicts, so this costs one validation pass rather than a full re-parse of the subtree.
    """
    return Element.model_validate(dict(record) | changes)


def build_candidate(baseline: Model, change_set: ChangeSet) -> Model:
    """Apply a change set to a baseline, producing a fully revalidated candidate.

    All or nothing: a command that cannot apply raises `CommandError` and the baseline is
    untouched. Cross-record validation is the caller's next step, in `validation/pipeline.py`.
    """
    if change_set.model_id != baseline.model_id:
        message = (
            f"change set targets {change_set.model_id!r} but the baseline is {baseline.model_id!r}"
        )
        raise CommandError(message)

    elements = {element.element_id: element for element in baseline.elements}
    relationships = {relation.relationship_id: relation for relation in baseline.relationships}

    for command in change_set.commands:
        match command:
            case AddElement():
                if command.element.element_id in elements:
                    raise CommandError(f"element {command.element.element_id!r} already exists")
                elements[command.element.element_id] = command.element
            case UpdateElement():
                current = _require(elements, command.element_id, "element")
                changes = {
                    field: value
                    for field, value in (
                        ("name", command.name),
                        ("description", command.description),
                        ("aliases", command.aliases),
                    )
                    if value is not None
                }
                elements[command.element_id] = _revalidate(current, **changes)
            case RenameElement():
                current = _require(elements, command.element_id, "element")
                if command.expected_name is not None and current.name != command.expected_name:
                    message = (
                        f"element {command.element_id!r} is named {current.name!r}, not "
                        f"{command.expected_name!r}"
                    )
                    raise CommandError(message)
                elements[command.element_id] = _revalidate(current, name=command.new_name)
            case RetireElement():
                current = _require(elements, command.element_id, "element")
                elements[command.element_id] = _revalidate(
                    current, lifecycle_state=LifecycleState.RETIRED
                )
            case AddRelationship():
                identity = command.relationship.relationship_id
                if identity in relationships:
                    raise CommandError(f"relationship {identity!r} already exists")
                relationships[identity] = command.relationship
            case RemoveRelationship():
                _require(relationships, command.relationship_id, "relationship")
                del relationships[command.relationship_id]
            case UpdateDetail():
                current = _require(elements, command.element_id, "element")
                elements[command.element_id] = _revalidate(current, detail=command.detail)

    return Model.model_validate(
        dict(baseline)
        | {
            "elements": tuple(elements.values()),
            "relationships": tuple(relationships.values()),
        }
    )


def _require[T](pool: dict[str, T], identity: str, label: str) -> T:
    found = pool.get(identity)
    if found is None:
        raise CommandError(f"{label} {identity!r} does not exist in the baseline")
    return found
