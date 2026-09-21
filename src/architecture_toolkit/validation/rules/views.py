"""View membership rules (CORE-07, PROJ-03).

Deferred from W1 to W7a with the reason stated — "no view definition exists to check membership
against" — and this is the wave that supplies one. Clearing `DEFERRALS[RuleFamily.VIEWS]` changes
the claim report every consumer reads: `cross_model_semantics` stops being `not_fully_checked`.

These are the questions a view raises that one record cannot answer. Whether a member id resolves
needs the rest of the model, so `ARCH-TOOL-CORE-001` §3F puts it here rather than in a Pydantic
validator; `domain/views.py` keeps the three questions a view can answer about itself.

**What is deliberately not here.** Re-deriving a `DERIVED` view's membership from its filter. A
rule's signature is `(Candidate, ValidationContext)` — no store, no release, no query session —
and `docs/plans/w7a-generator-foundations.md` says membership resolution uses the W5 query
context, which sits outside this layer. The honest W7a check is the record-local
`membership_policy_agrees_with_the_filter`; full re-derivation belongs with the generator that
materializes it.
"""

from collections.abc import Iterable

from architecture_toolkit.domain.references import (
    ElementReference,
    FieldReference,
    ReferenceTarget,
    RelationshipReference,
)
from architecture_toolkit.domain.views import MembershipPolicy
from architecture_toolkit.validation.candidate import Candidate
from architecture_toolkit.validation.context import ValidationContext
from architecture_toolkit.validation.diagnostics import Diagnostic, build_diagnostic
from architecture_toolkit.validation.rules import RuleFamily, rule

VIEW_REQUIREMENTS = frozenset({"CORE-07", "PROJ-03"})


@rule(
    rule_id="view-members-resolve",
    family=RuleFamily.VIEWS,
    emits={"CORE.VIEW.UNRESOLVED_MEMBER", "CORE.VIEW.UNRESOLVED_SCOPE"},
    requirements=VIEW_REQUIREMENTS,
    summary="Every object a view names exists in the model.",
)
def view_members_resolve(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
    """The reservation `validation/codes.py` has held since W1.

    A view is semantic governed content, so a member that resolves to nothing is a claim about an
    architecture that does not have one — and a generator would either omit it silently or emit a
    dangling notation object.
    """
    del context
    model = candidate.model
    elements = {element.element_id for element in model.elements}
    relationships = {relation.relationship_id for relation in model.relationships}

    for view in model.views:
        if view.scope is not None and view.scope not in elements:
            yield build_diagnostic(
                "CORE.VIEW.UNRESOLVED_SCOPE",
                message=(
                    f"view {view.view_id!r} is scoped to {view.scope!r}, which is not an element."
                ),
                rule_id="view-members-resolve",
                canonical_object_id=view.view_id,
                field_path="scope",
            )
        for member in view.included_element_ids:
            if member not in elements:
                yield build_diagnostic(
                    "CORE.VIEW.UNRESOLVED_MEMBER",
                    message=(
                        f"view {view.view_id!r} includes element {member!r}, which does not exist."
                    ),
                    rule_id="view-members-resolve",
                    canonical_object_id=view.view_id,
                    field_path="included_element_ids",
                    context=(("member", member),),
                )
        for member in view.included_relationship_ids:
            if member not in relationships:
                yield build_diagnostic(
                    "CORE.VIEW.UNRESOLVED_MEMBER",
                    message=(
                        f"view {view.view_id!r} includes relationship {member!r}, "
                        f"which does not exist."
                    ),
                    rule_id="view-members-resolve",
                    canonical_object_id=view.view_id,
                    field_path="included_relationship_ids",
                    context=(("member", member),),
                )


@rule(
    rule_id="view-member-endpoints-included",
    family=RuleFamily.VIEWS,
    emits={"CORE.VIEW.MEMBER_ENDPOINT_MISSING"},
    requirements=VIEW_REQUIREMENTS,
    summary="A relationship on a view has both of its elements on the same view.",
)
def view_member_endpoints_included(
    candidate: Candidate, context: ValidationContext
) -> Iterable[Diagnostic]:
    """A diagram cannot draw an edge to something that is not on it.

    Without this the generator has two bad options, and both lose information silently: omit the
    edge, or invent the node. `projections.md` forbids the second outright.
    """
    del context
    model = candidate.model
    endpoints = {
        relation.relationship_id: (relation.source_element_id, relation.target_element_id)
        for relation in model.relationships
    }

    for view in model.views:
        members = set(view.included_element_ids)
        for relationship_id in view.included_relationship_ids:
            pair = endpoints.get(relationship_id)
            if pair is None:
                continue  # `view-members-resolve` already reports this one.
            absent = sorted(endpoint for endpoint in pair if endpoint not in members)
            if absent:
                yield build_diagnostic(
                    "CORE.VIEW.MEMBER_ENDPOINT_MISSING",
                    message=(
                        f"view {view.view_id!r} includes relationship {relationship_id!r} without "
                        f"its endpoint(s) {absent}."
                    ),
                    rule_id="view-member-endpoints-included",
                    canonical_object_id=view.view_id,
                    relationship_id=relationship_id,
                    field_path="included_relationship_ids",
                )


@rule(
    rule_id="view-induced-membership-complete",
    family=RuleFamily.VIEWS,
    emits={"CORE.VIEW.INDUCED_MEMBERSHIP_STALE"},
    requirements=VIEW_REQUIREMENTS,
    summary="An induced view carries every relationship between the elements it includes.",
)
def view_induced_membership_complete(
    candidate: Candidate, context: ValidationContext
) -> Iterable[Diagnostic]:
    """What earns `MembershipPolicy.INDUCED` its place in the vocabulary.

    `induced` is a claim: the relationships are exactly those the members imply. A reader relies
    on it, and without a check an induced view and a stale explicit one are indistinguishable.
    A warning rather than an error, because the model is coherent — the view is merely out of date
    with respect to its own stated policy, which is a profile expectation.
    """
    del context
    model = candidate.model

    for view in model.views:
        if view.membership_policy is not MembershipPolicy.INDUCED:
            continue
        members = set(view.included_element_ids)
        implied = {
            relation.relationship_id
            for relation in model.relationships
            if relation.source_element_id in members and relation.target_element_id in members
        }
        missing = sorted(implied - set(view.included_relationship_ids))
        if missing:
            yield build_diagnostic(
                "CORE.VIEW.INDUCED_MEMBERSHIP_STALE",
                message=(
                    f"view {view.view_id!r} says its membership is induced but omits "
                    f"relationship(s) {missing} between elements it includes."
                ),
                rule_id="view-induced-membership-complete",
                canonical_object_id=view.view_id,
                field_path="included_relationship_ids",
            )


@rule(
    rule_id="binding-sits-in-the-view-it-names",
    family=RuleFamily.VIEWS,
    emits={"CORE.VIEW.BINDING_NOTATION_MISMATCH", "CORE.VIEW.BINDING_SUBJECT_NOT_A_MEMBER"},
    requirements=VIEW_REQUIREMENTS | {"PROJ-02"},
    summary="A binding that names a view is in that view's notation and in its membership.",
)
def binding_sits_in_the_view_it_names(
    candidate: Candidate, context: ValidationContext
) -> Iterable[Diagnostic]:
    """`NotationBinding.view_id` is a claim about two records, so only this layer can check it.

    `binding-view-resolves` asks whether the view exists. That is the weakest thing worth asking,
    and it was all W7a asked — which is how the shipped example came to carry a `bpmn` binding
    naming a `c4` view, with a subject the view's own membership excludes, and validate clean.

    Both halves matter to a generator and for the same reason: it has to place the object
    somewhere. A BPMN task in a C4 diagram has no shape to be drawn as, and an object the view
    does not contain has no place to be drawn in — so the generator would have to omit it silently
    or invent something, and `projections.md` forbids the second outright.
    """
    del context
    model = candidate.model
    views = {view.view_id: view for view in model.views}

    for binding in model.notation_bindings:
        view = views.get(binding.view_id) if binding.view_id is not None else None
        if view is None:
            continue  # `binding-view-resolves` reports an id that names nothing.

        if binding.notation is not view.notation:
            yield build_diagnostic(
                "CORE.VIEW.BINDING_NOTATION_MISMATCH",
                message=(
                    f"notation binding {binding.binding_id!r} is {binding.notation.value} and "
                    f"names view {view.view_id!r}, which is {view.notation.value}."
                ),
                rule_id="binding-sits-in-the-view-it-names",
                canonical_object_id=binding.binding_id,
                notation_object_id=binding.notation_object_id,
                field_path="view_id",
            )

        subject = _subject_identity(binding.subject)
        if subject is None:
            continue  # A release subject is not something a view can contain.
        members = set(view.included_element_ids) | set(view.included_relationship_ids)
        if subject not in members:
            yield build_diagnostic(
                "CORE.VIEW.BINDING_SUBJECT_NOT_A_MEMBER",
                message=(
                    f"notation binding {binding.binding_id!r} places {subject!r} in view "
                    f"{view.view_id!r}, whose membership does not include it."
                ),
                rule_id="binding-sits-in-the-view-it-names",
                canonical_object_id=binding.binding_id,
                notation_object_id=binding.notation_object_id,
                field_path="view_id",
                context=(("subject", subject),),
            )


def _subject_identity(subject: ReferenceTarget) -> str | None:
    """The canonical id a view could contain, or `None` for a subject no view holds.

    A field reference is answered by its element: a view contains the element, and the field is a
    place inside it. A release reference is not something a diagram draws.
    """
    match subject:
        case ElementReference() | FieldReference():
            return subject.element_id
        case RelationshipReference():
            return subject.relationship_id
        case _:
            return None


@rule(
    rule_id="binding-view-resolves",
    family=RuleFamily.VIEWS,
    emits={"CORE.VIEW.UNRESOLVED_BINDING"},
    requirements=VIEW_REQUIREMENTS,
    summary="A notation binding that names a view names one that exists.",
)
def binding_view_resolves(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
    """`NotationBinding.view_id` has pointed at nothing checkable since W1.

    Clearing the views deferral while leaving this unchecked would have been clearing it on a
    technicality: the field is half of what "view membership is semantic governed content" means,
    and it was the half nobody could validate.
    """
    del context
    model = candidate.model
    views = {view.view_id for view in model.views}

    for binding in model.notation_bindings:
        if binding.view_id is not None and binding.view_id not in views:
            yield build_diagnostic(
                "CORE.VIEW.UNRESOLVED_BINDING",
                message=(
                    f"notation binding {binding.binding_id!r} names view {binding.view_id!r}, "
                    f"which does not exist."
                ),
                rule_id="binding-view-resolves",
                canonical_object_id=binding.binding_id,
                notation_object_id=binding.notation_object_id,
                field_path="view_id",
            )
