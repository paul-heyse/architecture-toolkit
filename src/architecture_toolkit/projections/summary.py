"""The first typed projection DTO, and the Python builder that prepares it (CORE-32).

The pipeline `ARCH-TOOL-CORE-001` §2 draws is `canonical release -> Python projection builder ->
complete typed DTO -> Jinja -> text`, and this is the builder half of it for the one projection
W7a ships. Everything a template needs is decided here: which records appear, in what order, and
which presentation flags are true. A template iterates and branches on what it is handed.

**Why a DTO rather than the `Model` itself.** Handing a template the domain model would make every
field of every record reachable from a template, so "templates do not infer relationships" would
become a rule about what people remember not to write. `check_template` compares a template's
undeclared names against the DTO's fields, and that comparison is only worth anything if the DTO
is narrow.

**No counts a template could compute, and no counts it could not.** `element_count` is not here:
`summary.elements | length` is presentation arithmetic Jinja is good at. `has_unverified` is here,
because deciding what "unverified" means is a semantic decision and §10B puts those in Python.
"""

from pydantic import BaseModel, Field

from architecture_toolkit.domain.details import RequirementDetail, VerificationMethod
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest

__all__ = ["ElementRow", "ModelSummary", "RelationshipRow", "ViewRow", "summary_of"]


class _Row(BaseModel, frozen=True, strict=True, extra="forbid"):
    """A prepared presentation row. Frozen so a filter cannot edit what it was handed."""


class ElementRow(_Row):
    element_id: str
    name: str
    kind_id: str
    lifecycle_state: str
    description: str | None = None


class RelationshipRow(_Row):
    relationship_id: str
    relationship_type_id: str
    source_element_id: str
    target_element_id: str
    context_id: str | None = None


class ViewRow(_Row):
    view_id: str
    title: str
    view_type: str
    notation: str
    publication_state: str
    member_count: int
    scope: str | None = None


class ModelSummary(_Row):
    """Everything the model-summary template may see, and nothing else."""

    model_id: str
    schema_version: str
    profile_version: str
    model_digest: str
    elements: tuple[ElementRow, ...] = ()
    relationships: tuple[RelationshipRow, ...] = ()
    views: tuple[ViewRow, ...] = ()
    unverified_requirement_ids: tuple[str, ...] = ()
    generated_note: str = Field(min_length=1)


GENERATED_NOTE: str = (
    "Generated from the canonical model. Edits here are discarded on the next build; "
    "change the model instead."
)
"""On every generated artifact, because PROJ-01 says the canonical model is the only semantic
source and a file that does not say so invites somebody to edit it."""


def summary_of(model: Model) -> ModelSummary:
    """Prepare one model for rendering. Pure: no clock, no store, no network.

    Ordering is by identity rather than authored order, because authored order is presentation
    (CORE-21) and a generated artifact that reshuffled when somebody moved a YAML block would
    produce a different digest for the same architecture.
    """
    unverified = tuple(
        sorted(
            element.element_id
            for element in model.elements
            if isinstance(element.detail, RequirementDetail)
            and element.detail.verification_method is VerificationMethod.NOT_ESTABLISHED
        )
    )
    return ModelSummary(
        model_id=model.model_id,
        schema_version=model.schema_version,
        profile_version=model.profile_version,
        model_digest=model_digest(model),
        elements=tuple(
            sorted(
                (
                    ElementRow(
                        element_id=element.element_id,
                        name=element.name,
                        kind_id=element.kind_id,
                        lifecycle_state=element.lifecycle_state.value,
                        description=element.description,
                    )
                    for element in model.elements
                ),
                key=lambda row: row.element_id,
            )
        ),
        relationships=tuple(
            sorted(
                (
                    RelationshipRow(
                        relationship_id=relation.relationship_id,
                        relationship_type_id=relation.relationship_type_id,
                        source_element_id=relation.source_element_id,
                        target_element_id=relation.target_element_id,
                        context_id=relation.context_id,
                    )
                    for relation in model.relationships
                ),
                key=lambda row: row.relationship_id,
            )
        ),
        views=tuple(
            sorted(
                (
                    ViewRow(
                        view_id=view.view_id,
                        title=view.title,
                        view_type=view.view_type.value,
                        notation=view.notation.value,
                        publication_state=view.publication_state.value,
                        # Computed here rather than in the template: `member_count` is a property
                        # on the record and a template that reached for it would be reaching past
                        # the DTO, which is what CORE-32 exists to prevent.
                        member_count=view.member_count,
                        scope=view.scope,
                    )
                    for view in model.views
                ),
                key=lambda row: row.view_id,
            )
        ),
        unverified_requirement_ids=unverified,
        generated_note=GENERATED_NOTE,
    )
