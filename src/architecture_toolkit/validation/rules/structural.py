"""Identity, endpoint and containment rules (CORE-07).

These are the checks `Model.structural_invariants` used to do inline, plus the ones the registry
makes possible for the first time. They live here because `ARCH-TOOL-CORE-001` §3F puts
foreign-key resolution, relationship endpoint semantics and graph rules explicitly outside
record-local validators: a Pydantic validator sees one record, and none of these questions can
be answered from one record.

Containment uses `graphlib.TopologicalSorter` from the standard library rather than NetworkX.
DATA-01 gives NetworkX a bounded role as a derived read surface behind W5's `ArchitectureGraph`
facade, and reaching for it here would put a second graph entry point in the tree before the
first one exists.
"""

from collections import Counter
from collections.abc import Iterable
from graphlib import CycleError, TopologicalSorter

from architecture_toolkit.domain.registry import CanonicalDirection
from architecture_toolkit.domain.semantics import MODEL_COLLECTIONS
from architecture_toolkit.validation.candidate import Candidate
from architecture_toolkit.validation.context import ValidationContext
from architecture_toolkit.validation.diagnostics import Diagnostic, build_diagnostic
from architecture_toolkit.validation.rules import RuleFamily, rule

ACYCLIC_RULE = "acyclic"
SINGLE_PARENT_RULE = "single-parent"


@rule(
    rule_id="unique-identities",
    family=RuleFamily.IDENTITY,
    emits={"CORE.DOMAIN.DUPLICATE_ID"},
    requirements={"CORE-07", "DATA-03", "DATA-04", "DATA-05"},
    summary="No two records in one model claim the same identity.",
)
def unique_identities(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
    """Every top-level collection, derived from `MODEL_COLLECTIONS` rather than listed.

    It used to name four of the six by hand, so duplicate `link_id` and duplicate `binding_id`
    went unchecked from W1 until now — silently, because a rule that does not look at a
    collection reports nothing about it and reports nothing about reporting nothing. Deriving
    the loop makes a new collection covered the day it is declared rather than the day somebody
    remembers this function.

    `MODEL_COLLECTIONS` is the same pair list `stamp_digests` and the identity-delta recipe use,
    so "which collections have identities" is answered once.
    """
    del context
    model = candidate.model
    for collection, key in MODEL_COLLECTIONS:
        identities = [str(getattr(record, key)) for record in getattr(model, collection)]
        for identity, count in sorted(Counter(identities).items()):
            if count > 1:
                yield build_diagnostic(
                    "CORE.DOMAIN.DUPLICATE_ID",
                    message=f"{count} {collection} records share the identity {identity!r}.",
                    rule_id="unique-identities",
                    canonical_object_id=identity,
                )


@rule(
    rule_id="endpoints-resolve",
    family=RuleFamily.IDENTITY,
    emits={"CORE.RELATION.UNRESOLVED_ENDPOINT"},
    requirements={"CORE-07", "DATA-03"},
    summary="Every relationship endpoint names an element in this model.",
)
def endpoints_resolve(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
    del context
    model = candidate.model
    known = {element.element_id for element in model.elements}
    for relation in model.relationships:
        for side, element_id in (
            ("source_element_id", relation.source_element_id),
            ("target_element_id", relation.target_element_id),
        ):
            if element_id not in known:
                yield build_diagnostic(
                    "CORE.RELATION.UNRESOLVED_ENDPOINT",
                    message=f"{element_id!r} does not resolve.",
                    rule_id="endpoints-resolve",
                    relationship_id=relation.relationship_id,
                    field_path=f"relationships.{relation.relationship_id}.{side}",
                    context=(("endpoint", element_id), ("side", side)),
                )


@rule(
    rule_id="endpoint-kinds",
    family=RuleFamily.ENDPOINTS,
    emits={"CORE.RELATION.UNKNOWN_TYPE", "CORE.RELATION.ENDPOINT_KIND_NOT_PERMITTED"},
    requirements={"CORE-07", "DATA-05"},
    summary="Endpoint kinds are permitted for the relationship type by the active profile.",
)
def endpoint_kinds(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
    del context
    model, profile = candidate.model, candidate.profile
    kind_of = {element.element_id: element.kind_id for element in model.elements}
    for relation in model.relationships:
        entry = profile.relationship_types_by_id.get(relation.relationship_type_id)
        if entry is None:
            yield build_diagnostic(
                "CORE.RELATION.UNKNOWN_TYPE",
                message=(
                    f"relationship type {relation.relationship_type_id!r} is not defined by "
                    f"profile {profile.profile_id!r}."
                ),
                rule_id="endpoint-kinds",
                relationship_id=relation.relationship_id,
            )
            continue
        for side, element_id, permitted in (
            ("source", relation.source_element_id, entry.permitted_source_kinds),
            ("target", relation.target_element_id, entry.permitted_target_kinds),
        ):
            kind = kind_of.get(element_id)
            if kind is not None and kind not in permitted:
                yield build_diagnostic(
                    "CORE.RELATION.ENDPOINT_KIND_NOT_PERMITTED",
                    message=(
                        f"{relation.relationship_type_id!r} does not permit a {kind!r} "
                        f"{side}; permitted: {', '.join(sorted(permitted))}."
                    ),
                    rule_id="endpoint-kinds",
                    relationship_id=relation.relationship_id,
                    canonical_object_id=element_id,
                    field_path=f"relationships.{relation.relationship_id}.{side}_element_id",
                    context=(("kind", kind), ("side", side)),
                )


@rule(
    rule_id="no-self-loop",
    family=RuleFamily.ENDPOINTS,
    emits={"CORE.RELATION.SELF_LOOP"},
    requirements={"CORE-07", "DATA-05"},
    summary="A relationship type declaring no-self-loop does not join an element to itself.",
)
def no_self_loop(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
    del context
    for relation in candidate.model.relationships:
        entry = candidate.profile.relationship_types_by_id.get(relation.relationship_type_id)
        if entry is None or "no-self-loop" not in entry.validation_rule_ids:
            continue
        if relation.source_element_id == relation.target_element_id:
            yield build_diagnostic(
                "CORE.RELATION.SELF_LOOP",
                message=(
                    f"{relation.relationship_type_id!r} joins {relation.source_element_id!r} "
                    f"to itself."
                ),
                rule_id="no-self-loop",
                relationship_id=relation.relationship_id,
            )


@rule(
    rule_id="no-duplicate-inverse",
    family=RuleFamily.ENDPOINTS,
    emits={"CORE.RELATION.DUPLICATE_INVERSE"},
    requirements={"CORE-07", "DATA-06"},
    summary="Both directions of a symmetric relationship are never stored (DATA-06).",
)
def no_duplicate_inverse(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
    del context
    seen: dict[tuple[str, str, str], str] = {}
    for relation in candidate.model.relationships:
        entry = candidate.profile.relationship_types_by_id.get(relation.relationship_type_id)
        if entry is None or entry.canonical_direction is not CanonicalDirection.SYMMETRIC:
            continue
        pair = tuple(sorted((relation.source_element_id, relation.target_element_id)))
        key = (relation.relationship_type_id, pair[0], pair[1])
        first = seen.get(key)
        if first is not None:
            yield build_diagnostic(
                "CORE.RELATION.DUPLICATE_INVERSE",
                message=(
                    f"{relation.relationship_id!r} mirrors {first!r}; store one canonical "
                    f"direction and derive the inverse view."
                ),
                rule_id="no-duplicate-inverse",
                relationship_id=relation.relationship_id,
                context=(("mirrors", first),),
            )
            continue
        seen[key] = relation.relationship_id


@rule(
    rule_id=ACYCLIC_RULE,
    family=RuleFamily.CONTAINMENT,
    emits={"CORE.CONTAINMENT.CYCLE"},
    requirements={"CORE-07", "DATA-05"},
    summary="A relationship type declared acyclic forms no cycle.",
)
def acyclic(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
    del context
    for entry in candidate.profile.relationship_types:
        if ACYCLIC_RULE not in entry.validation_rule_ids:
            continue
        graph: dict[str, set[str]] = {}
        for relation in candidate.model.relationships:
            if relation.relationship_type_id != entry.relationship_type_id:
                continue
            graph.setdefault(relation.target_element_id, set()).add(relation.source_element_id)
            graph.setdefault(relation.source_element_id, set())
        try:
            TopologicalSorter(graph).prepare()
        except CycleError as detected:
            members = [str(node) for node in detected.args[1]]
            yield build_diagnostic(
                "CORE.CONTAINMENT.CYCLE",
                message=(f"{entry.relationship_type_id!r} forms a cycle: {' -> '.join(members)}."),
                rule_id=ACYCLIC_RULE,
                context=(("relationship_type", entry.relationship_type_id),),
            )


@rule(
    rule_id=SINGLE_PARENT_RULE,
    family=RuleFamily.CONTAINMENT,
    emits={"CORE.CONTAINMENT.MULTIPLE_PARENTS"},
    requirements={"CORE-07", "DATA-05"},
    summary="An element declared single-parent has at most one container.",
)
def single_parent(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
    del context
    for entry in candidate.profile.relationship_types:
        if SINGLE_PARENT_RULE not in entry.validation_rule_ids:
            continue
        parents: dict[str, list[str]] = {}
        for relation in candidate.model.relationships:
            if relation.relationship_type_id == entry.relationship_type_id:
                parents.setdefault(relation.target_element_id, []).append(
                    relation.source_element_id
                )
        for child, found in sorted(parents.items()):
            if len(found) > 1:
                yield build_diagnostic(
                    "CORE.CONTAINMENT.MULTIPLE_PARENTS",
                    message=(
                        f"{child!r} is contained by {len(found)} parents: "
                        f"{', '.join(sorted(found))}."
                    ),
                    rule_id=SINGLE_PARENT_RULE,
                    canonical_object_id=child,
                )
