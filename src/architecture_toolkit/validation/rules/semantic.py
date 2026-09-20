"""Evidence, interface and workflow rules (CORE-07, DATA-07, DATA-09, DATA-41).

The rules here carry the dispositions that make DATA-41 operational. An unresolved reference is
a hard structural error — the link points at nothing. A behaviour step with no participating
element is an *evidence gap* at INFO, because a manual process legitimately has no application
behind it, and `ARCH-TOOL-DATA-001` §10F is explicit that attaching one to complete a coverage
matrix is the wrong repair.

That difference is why `Disposition` is a separate axis from `Severity`. Both of those findings
could be called "warning"; only one of them is something to fix.
"""

from collections.abc import Iterable

from architecture_toolkit.domain.details import (
    BehaviorNodeType,
    DataSchemaDetail,
    InterfaceDetail,
)
from architecture_toolkit.validation.candidate import Candidate
from architecture_toolkit.validation.context import ValidationContext
from architecture_toolkit.validation.diagnostics import Diagnostic, build_diagnostic
from architecture_toolkit.validation.rules import RuleFamily, rule

# Only work gets done by someone. A gateway routes and an event happens, so neither having a
# participant is normal rather than a gap — reporting them would bury the one case that matters
# (a task nobody performs) under noise. Found by running the rule against the example.
PERFORMED_NODE_TYPES = frozenset(
    {BehaviorNodeType.TASK, BehaviorNodeType.MANUAL_TASK, BehaviorNodeType.SUBPROCESS}
)


def _subject_id(subject: object) -> tuple[str, str]:
    """Render a `ReferenceTarget` as (kind, id) without caring which variant it is."""
    kind = str(getattr(subject, "subject_kind", "unknown"))
    for attribute in ("element_id", "relationship_id", "release_id"):
        found = getattr(subject, attribute, None)
        if found is not None:
            return kind, str(found)
    return kind, ""


@rule(
    rule_id="reference-links-resolve",
    family=RuleFamily.EVIDENCE,
    emits={"CORE.EVIDENCE.UNRESOLVED_SUBJECT", "CORE.EVIDENCE.UNRESOLVED_REFERENCE"},
    requirements={"CORE-07", "DATA-09"},
    summary="Every evidence link names a reference and a subject that exist.",
)
def reference_links_resolve(
    candidate: Candidate, context: ValidationContext
) -> Iterable[Diagnostic]:
    del context
    model = candidate.model
    elements = {element.element_id for element in model.elements}
    relationships = {relation.relationship_id for relation in model.relationships}
    references = {reference.reference_id for reference in model.references}
    for link in model.reference_links:
        if link.reference_id not in references:
            yield build_diagnostic(
                "CORE.EVIDENCE.UNRESOLVED_REFERENCE",
                message=f"link {link.link_id!r} names unknown reference {link.reference_id!r}.",
                rule_id="reference-links-resolve",
                canonical_object_id=link.link_id,
            )
        kind, identity = _subject_id(link.subject)
        pool = {"element": elements, "field": elements, "relationship": relationships}.get(kind)
        if pool is not None and identity not in pool:
            yield build_diagnostic(
                "CORE.EVIDENCE.UNRESOLVED_SUBJECT",
                message=f"link {link.link_id!r} addresses unknown {kind} {identity!r}.",
                rule_id="reference-links-resolve",
                canonical_object_id=link.link_id,
                context=(("subject_kind", kind), ("subject_id", identity)),
            )


@rule(
    rule_id="contradicted-evidence-needs-review",
    family=RuleFamily.EVIDENCE,
    emits={"CORE.EVIDENCE.CONTRADICTED"},
    requirements={"CORE-07", "DATA-09", "DATA-41"},
    summary="A contradicting reference is surfaced for human review, never resolved away.",
)
def contradicted_evidence_needs_review(
    candidate: Candidate, context: ValidationContext
) -> Iterable[Diagnostic]:
    del context
    for link in candidate.model.reference_links:
        if link.link_role != "contradicts":
            continue
        kind, identity = _subject_id(link.subject)
        yield build_diagnostic(
            "CORE.EVIDENCE.CONTRADICTED",
            message=(
                f"reference {link.reference_id!r} contradicts the {kind} {identity!r}. "
                f"This is evidence to keep, not a defect to clear."
            ),
            rule_id="contradicted-evidence-needs-review",
            canonical_object_id=identity or link.link_id,
        )


@rule(
    rule_id="detail-family-permitted",
    family=RuleFamily.INTERFACES,
    emits={"CORE.INTERFACE.DETAIL_NOT_PERMITTED"},
    requirements={"CORE-07", "DATA-07"},
    summary="An element carries only detail families its kind permits in the active profile.",
)
def detail_family_permitted(
    candidate: Candidate, context: ValidationContext
) -> Iterable[Diagnostic]:
    del context
    for element in candidate.model.elements:
        if element.detail is None:
            continue
        kind = candidate.profile.kinds_by_id.get(element.kind_id)
        if kind is None or element.detail.detail_family in kind.permitted_detail_families:
            continue
        yield build_diagnostic(
            "CORE.INTERFACE.DETAIL_NOT_PERMITTED",
            message=(
                f"{element.kind_id!r} does not permit a "
                f"{element.detail.detail_family.value!r} detail in profile "
                f"{candidate.profile.profile_id!r}."
            ),
            rule_id="detail-family-permitted",
            canonical_object_id=element.element_id,
            field_path=f"elements.{element.element_id}.detail",
        )


@rule(
    rule_id="schema-references-resolve",
    family=RuleFamily.INTERFACES,
    emits={"CORE.INTERFACE.UNRESOLVED_SCHEMA", "CORE.INTERFACE.UNRESOLVED_FOREIGN_KEY"},
    requirements={"CORE-07", "DATA-07", "DATA-30"},
    summary="Interface schema references and schema foreign keys name elements that exist.",
)
def schema_references_resolve(
    candidate: Candidate, context: ValidationContext
) -> Iterable[Diagnostic]:
    del context
    known = {element.element_id for element in candidate.model.elements}
    for element in candidate.model.elements:
        detail = element.detail
        if isinstance(detail, InterfaceDetail):
            for label, target in (
                ("request_schema_id", detail.request_schema_id),
                ("response_schema_id", detail.response_schema_id),
            ):
                if target is not None and target not in known:
                    yield build_diagnostic(
                        "CORE.INTERFACE.UNRESOLVED_SCHEMA",
                        message=f"{label} {target!r} does not resolve.",
                        rule_id="schema-references-resolve",
                        canonical_object_id=element.element_id,
                        field_path=f"elements.{element.element_id}.detail.{label}",
                    )
        elif isinstance(detail, DataSchemaDetail):
            for field in detail.fields:
                target = field.references_element_id
                if target is not None and target not in known:
                    yield build_diagnostic(
                        "CORE.INTERFACE.UNRESOLVED_FOREIGN_KEY",
                        message=(
                            f"field {field.field_id!r} references unknown element {target!r}."
                        ),
                        rule_id="schema-references-resolve",
                        canonical_object_id=element.element_id,
                        field_path=(
                            f"elements.{element.element_id}.detail.fields.{field.field_id}"
                            ".references_element_id"
                        ),
                    )


@rule(
    rule_id="workflow-participants",
    family=RuleFamily.WORKFLOWS,
    emits={"CORE.WORKFLOW.UNRESOLVED_PARTICIPANT", "CORE.WORKFLOW.NO_PARTICIPANT"},
    requirements={"CORE-07", "DATA-08", "DATA-30", "DATA-41"},
    summary="Participants resolve; a manual step is reported rather than failed.",
)
def workflow_participants(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
    del context
    known = {element.element_id for element in candidate.model.elements}
    for element in candidate.model.elements:
        detail = element.detail
        if detail is None or detail.detail_family != "behavior":
            continue
        for node in detail.nodes:
            if node.participant_element_id is None:
                if node.node_type in PERFORMED_NODE_TYPES:
                    yield build_diagnostic(
                        "CORE.WORKFLOW.NO_PARTICIPANT",
                        message=(
                            f"behaviour node {node.node_id!r} has no participating element. "
                            f"Expected for a manual step."
                        ),
                        rule_id="workflow-participants",
                        canonical_object_id=element.element_id,
                        context=(
                            ("node_id", node.node_id),
                            ("node_type", node.node_type.value),
                        ),
                    )
                continue
            if node.participant_element_id not in known:
                yield build_diagnostic(
                    "CORE.WORKFLOW.UNRESOLVED_PARTICIPANT",
                    message=(
                        f"behaviour node {node.node_id!r} names unknown participant "
                        f"{node.participant_element_id!r}."
                    ),
                    rule_id="workflow-participants",
                    canonical_object_id=element.element_id,
                )
    for interaction in candidate.model.interactions:
        for participant in interaction.participants:
            if participant.element_id not in known:
                yield build_diagnostic(
                    "CORE.WORKFLOW.UNRESOLVED_PARTICIPANT",
                    message=(
                        f"interaction {interaction.interaction_id!r} names unknown participant "
                        f"{participant.element_id!r}."
                    ),
                    rule_id="workflow-participants",
                    canonical_object_id=interaction.interaction_id,
                )
        for moved in interaction.moved_object_ids:
            if moved not in known:
                yield build_diagnostic(
                    "CORE.WORKFLOW.UNRESOLVED_PARTICIPANT",
                    message=(
                        f"interaction {interaction.interaction_id!r} moves unknown object "
                        f"{moved!r}."
                    ),
                    rule_id="workflow-participants",
                    canonical_object_id=interaction.interaction_id,
                )
