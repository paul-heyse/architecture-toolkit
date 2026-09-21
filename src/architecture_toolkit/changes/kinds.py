"""What a change is, and whether it enters the architectural narrative (DATA-26, DATA-31).

Two axes, not one, because the hard gate needs an answer to two different questions and a single
enum can only answer one. `ChangeKind` says **what changed** — the list `ARCH-TOOL-DATA-001` §6
names, grounded in fields that exist rather than in categories somebody might want. `ChangeNature`
says **whether it belongs in the change narrative at all**, which is `projections.md`'s
seven-way classification and the thing the gate is actually about:

> Layout/presentation-only changes do not masquerade as semantic model changes.

Collapsing them loses the case the gate exists for. A `NotationBinding` edit and an
`InterfaceDetail` edit are both "a record changed"; one is a diagram detail and the other is a
contract. And a single axis forces a choice nobody should have to make: either
`NOTATION_MAPPING_CHANGED` is its own kind and the reader cannot tell it from a layout edit, or it
is a layout kind and a re-mapped model becomes indistinguishable from a re-authored one — which is
exactly what `domain/notation.py` says DATA-31 forbids.

**`ChangeNature` is defined at all seven, not at the three reachable today.** `projections.md`
already names them, W7a and W8 deliver the records that make the last two reachable, and defining
the wider set now means a later wave extends the classification table rather than migrating every
stored change record. This is the same reservation `validation/taxonomy.py` makes for
`ENGINEERING_QUALIFICATION` and W4 makes for the manifest's projection fields.

**Whether a nature enters the narrative is declared on the nature, never decided at a call site.**
`NARRATIVE_NATURES` below is the one place the gate is expressed, so a filter cannot drift from
the classification it filters.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "NARRATIVE_NATURES",
    "NEVER_EMITTED",
    "UNREACHABLE_NATURES",
    "ChangeKind",
    "ChangeNature",
    "ChangeRule",
    "Traversal",
]


class ChangeNature(StrEnum):
    """Whether a change is architecture or presentation. `projections.md`, all seven.

    The first three are governed content and carry the narrative; the last four are provenance
    about how the architecture was drawn, published or rendered, and never do.
    """

    # -- narrative-bearing --------------------------------------------------------------------
    CANONICAL_SEMANTIC = "canonical_semantic"
    # `projections.md`: "View membership is semantic governed content." Which view an object
    # appears in is a modelling decision; where the box sits in that view is not.
    VIEW_MEMBERSHIP = "view_membership"
    # §12H includes the mapping profile in semantic identity "when a changed mapping would change
    # the semantics represented in a standards projection".
    NOTATION_MAPPING = "notation_mapping"

    # -- presentation provenance --------------------------------------------------------------
    LAYOUT_ONLY = "layout_only"
    RENDERER_TOOLCHAIN = "renderer_toolchain"
    # Reserved. `LayoutProfile` arrives with W7a (PROJ-04) and the portal with W8, so no field
    # reachable from `Model` can carry either today. `changes/classification.py` asserts that no
    # rule uses them, in both directions, so the reservation is checked rather than commented.
    STYLE_THEME_ONLY = "style_theme_only"
    PUBLICATION_NAVIGATION_ONLY = "publication_navigation_only"


NARRATIVE_NATURES: Final[frozenset[ChangeNature]] = frozenset(
    {
        ChangeNature.CANONICAL_SEMANTIC,
        ChangeNature.VIEW_MEMBERSHIP,
        ChangeNature.NOTATION_MAPPING,
    }
)
"""The natures a change narrative reports. Everything else is how the model was drawn."""

UNREACHABLE_NATURES: Final[Mapping[ChangeNature, str]] = MappingProxyType(
    {
        ChangeNature.STYLE_THEME_ONLY: "W7a — no LayoutProfile exists before PROJ-04",
        ChangeNature.PUBLICATION_NAVIGATION_ONLY: "W8 — no portal bundle exists before PROJ-35",
    }
)
"""Declared but unusable, each with the wave that makes it reachable.

The same shape `validation/pipeline.py::_UNREACHABLE` uses: a reserved value pairs with a prose
scope string rather than a comment, so the reservation can be asserted.
"""


class ChangeKind(StrEnum):
    """What changed. `ARCH-TOOL-DATA-001` §6's list, widened only where a field forced it.

    §6 names nine changes to distinguish. Several of them fan out once the actual records are in
    view — "evidence or qualification changed" is five independent status dimensions under
    DATA-29, and refusing to fan it out would re-collapse the axis W1 spent a module separating.
    Nothing here is invented: every member is the classification of at least one real field, and
    `changes/classification.py` asserts that in both directions.
    """

    # -- presence: a record appeared or vanished ----------------------------------------------
    ELEMENT_ADDED = "element_added"
    ELEMENT_REMOVED = "element_removed"
    RELATIONSHIP_ADDED = "relationship_added"
    RELATIONSHIP_REMOVED = "relationship_removed"
    INTERACTION_ADDED = "interaction_added"
    INTERACTION_REMOVED = "interaction_removed"
    REFERENCE_ADDED = "reference_added"
    REFERENCE_REMOVED = "reference_removed"
    EVIDENCE_LINK_ADDED = "evidence_link_added"
    EVIDENCE_LINK_REMOVED = "evidence_link_removed"
    NOTATION_BINDING_ADDED = "notation_binding_added"
    NOTATION_BINDING_REMOVED = "notation_binding_removed"

    # -- element identity and lifecycle -------------------------------------------------------
    ELEMENT_RENAMED = "element_renamed"
    # Not a presence kind. `RetireElement` sets `lifecycle_state` and leaves the record in place,
    # so a retirement is a *changed* identity — reporting it as a removal would be the retire/add
    # confusion the wave exists to prevent, wearing the other hat.
    ELEMENT_RETIRED = "element_retired"
    ELEMENT_REACTIVATED = "element_reactivated"
    ELEMENT_REPLACED = "element_replaced"
    ELEMENT_RETYPED = "element_retyped"

    # -- relationship semantics ---------------------------------------------------------------
    RELATIONSHIP_ENDPOINT_CHANGED = "relationship_endpoint_changed"
    RELATIONSHIP_RETYPED = "relationship_retyped"
    RELATIONSHIP_CONTEXT_CHANGED = "relationship_context_changed"

    # -- typed detail -------------------------------------------------------------------------
    DETAIL_ADDED = "detail_added"
    DETAIL_REMOVED = "detail_removed"
    DETAIL_FAMILY_CHANGED = "detail_family_changed"
    INTERFACE_CONTRACT_CHANGED = "interface_contract_changed"
    DATA_SCHEMA_CHANGED = "data_schema_changed"
    BEHAVIOR_CHANGED = "behavior_changed"
    DEPLOYMENT_CHANGED = "deployment_changed"
    REQUIREMENT_APPLICABILITY_CHANGED = "requirement_applicability_changed"
    REQUIREMENT_VERIFICATION_CHANGED = "requirement_verification_changed"

    # -- the five status dimensions, separate because DATA-29 requires them separate -----------
    DISPOSITION_CHANGED = "disposition_changed"
    IMPLEMENTATION_STATE_CHANGED = "implementation_state_changed"
    QUALIFICATION_CHANGED = "qualification_changed"
    ACCEPTANCE_CHANGED = "acceptance_changed"
    EVIDENCE_REVIEW_CHANGED = "evidence_review_changed"

    # -- interaction, evidence and annotation -------------------------------------------------
    INTERACTION_CHANGED = "interaction_changed"
    INTERACTION_PARTICIPANTS_CHANGED = "interaction_participants_changed"
    EVIDENCE_CHANGED = "evidence_changed"
    EVIDENCE_SUBJECT_CHANGED = "evidence_subject_changed"
    ANNOTATION_CHANGED = "annotation_changed"

    # -- notation, view and presentation ------------------------------------------------------
    NOTATION_MAPPING_CHANGED = "notation_mapping_changed"
    BINDING_RESUBJECTED = "binding_resubjected"
    VIEW_MEMBERSHIP_CHANGED = "view_membership_changed"
    DISPLAY_NAME_CHANGED = "display_name_changed"
    LAYOUT_LINK_CHANGED = "layout_link_changed"
    PROJECTION_PROVENANCE_CHANGED = "projection_provenance_changed"

    # -- model-level --------------------------------------------------------------------------
    SCHEMA_VERSION_CHANGED = "schema_version_changed"
    PROFILE_VERSION_CHANGED = "profile_version_changed"

    # -- classified, and structurally never emitted -------------------------------------------
    # Every field below has a rule so that it cannot hide in an exclusion set — an exclusion set
    # is a second place a field can escape classification, and `NEVER_EMITTED` makes the claim
    # checkable instead: `tests/unit/test_change_classification.py` asserts the differ emits none
    # of these for any pair of models.
    #
    # A `Model` collection field. `semantic_delta` answers membership; the field differ does not.
    COLLECTION_MEMBERSHIP = "collection_membership"
    # An identity or match key: `model_id`, a record id, or the key a nested collection is paired
    # by. It cannot differ between two versions *of the same record*, because it is what made them
    # the same record.
    RECORD_IDENTITY = "record_identity"
    # Part of a value reported as one change at the owning field — a `ReferenceTarget`'s
    # components, an `Extension`'s, an `InteractionParticipant`'s. Re-pointing an address is one
    # fact; which half of the address moved is not separately meaningful.
    REPORTED_AS_A_WHOLE = "reported_as_a_whole"
    # Stamped by `stamp_digests`, stripped by `normalize_record` at every depth.
    DIGEST_RESTAMPED = "digest_restamped"
    # A field whose children carry the change: `Element.status`, `InterfaceDetail.transport`, an
    # identity-keyed collection of records. Reporting "status changed" instead of
    # "status.technical_qualification changed" would re-collapse the axis DATA-29 separates.
    CONTAINER = "container"

    # -- the residual -------------------------------------------------------------------------
    # `Reference.authority`, `InterfaceDetail.idempotency_description` and their kind have no
    # named category in any contract. A residual is unavoidable; what makes it safe is that it is
    # never a lookup default, that it is `CANONICAL_SEMANTIC` so an unclassified field is noisy
    # rather than silently invisible, and that `tests/unit/test_change_classification.py` pins
    # both a ceiling on its size and a list of fields that must never reach it.
    FIELD_MODIFIED = "field_modified"


class Traversal(StrEnum):
    """Whether the differ reports a field here, descends through it, or can never see it.

    Declared beside the classification rather than inferred, because inference is where a walk
    quietly stops descending and the table quietly agrees with it. `COLLECTION_ORDER` cannot
    answer this — it knows nothing about `Element.status` or `InterfaceDetail.transport`, neither
    of which is a tuple — so a second table would have been the alternative, and a second table
    drifts from the first.
    """

    LEAF = "leaf"
    DESCEND = "descend"
    # Structurally cannot differ between two versions of the same record — an identity or match
    # key — or is never reached because its parent is a leaf. The differ raises rather than
    # emitting, so "never emitted" is enforced instead of asserted.
    NEVER = "never"


@dataclass(frozen=True, slots=True)
class ChangeRule:
    """How one field's change is classified.

    A record rather than a tuple for the reason `CollectionOrder` is one: there is somewhere to
    put the third thing a later wave wants without re-keying the table.

    `refine` maps a canonical new value to a narrower kind, which exactly one field needs today —
    `Element.lifecycle_state`, where "retired" and "reactivated" are different facts about the
    same field. Declarative on purpose: a table of callables is code with extra steps, cannot be
    printed or diffed, and cannot be asserted total.
    """

    kind: ChangeKind
    nature: ChangeNature
    traversal: Traversal = Traversal.LEAF
    refine: tuple[tuple[str, ChangeKind], ...] = ()

    def resolve(self, after: object) -> ChangeKind:
        """The kind for this change, narrowed by the new value where the field declares it."""
        for value, narrowed in self.refine:
            if after == value:
                return narrowed
        return self.kind

    @property
    def in_narrative(self) -> bool:
        return self.nature in NARRATIVE_NATURES


NEVER_EMITTED: Final[frozenset[ChangeKind]] = frozenset(
    {
        ChangeKind.COLLECTION_MEMBERSHIP,
        ChangeKind.RECORD_IDENTITY,
        ChangeKind.REPORTED_AS_A_WHOLE,
        ChangeKind.DIGEST_RESTAMPED,
        ChangeKind.CONTAINER,
    }
)
"""Kinds that exist so their fields are classified, and that no field change may carry.

Each of the five is a different reason a declared field is not a field-level change, kept apart
because the reasons are different.

`tests/integration/test_observed_change_kinds.py` asserts the differ produces none of them over a
corpus that edits one model in every way this vocabulary can express — and, from the other
direction, that every kind *not* in this set is produced by something. Before that corpus existed
this docstring claimed a test that did not exist: the only assertions were set algebra over two
frozen constants, which would have passed with a differ that returned nothing for every input.
"""
