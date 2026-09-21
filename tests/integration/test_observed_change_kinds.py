"""Every classification DATA-26 names is produced by something, not merely declared (DATA-26).

`CHANGE_CLASSIFICATION` is asserted total — every field of every record has a rule — and until now
nothing asserted that the rules *produce* the right kinds on real data.
`test_every_declared_kind_classifies_at_least_one_real_field` proves table membership, which is a
different claim: it would pass with a differ that returned nothing for every input.

Measured before this file existed: thirty of the fifty-three `ChangeKind` members were never named
in any test, and three of DATA-26's nine categories had no test at all — relationship added,
relationship endpoint changed, and requirement applicability changed. The second of those is the
sharpest, because `changes/classification.py` introduces it as *"the case
`queries/algorithms.py::compare_architecture_releases` reports as no change today"* — a fix
advertised and never demonstrated.

So the corpus below is the guard for the class rather than for those three instances. It edits one
model in every way the classification vocabulary can express, collects what the differ actually
emits, and refuses a declared kind that nothing produces. A later wave adding a kind has to produce
it or say why not.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from architecture_toolkit.changes.diff import model_changes
from architecture_toolkit.changes.kinds import NEVER_EMITTED, ChangeKind, ChangeNature
from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.details import (
    Applicability,
    BehaviorDetail,
    DataSchemaDetail,
    DeploymentDetail,
    VerificationMethod,
)
from architecture_toolkit.domain.extensions import Extension
from architecture_toolkit.domain.model import Element, Model, Relationship
from architecture_toolkit.domain.notation import Notation
from architecture_toolkit.domain.references import ElementReference, LinkRole
from architecture_toolkit.domain.status import (
    ClientAcceptance,
    DesignDisposition,
    EvidenceReview,
    ImplementationState,
    LifecycleState,
    TechnicalQualification,
)
from architecture_toolkit.domain.views import (
    FilterDimension,
    FilterMode,
    MembershipPolicy,
    PublicationState,
    ViewDefinition,
    ViewFilter,
    ViewType,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "minimal" / "model.yaml"


def _view() -> ViewDefinition:
    """The view every view case starts from. Explicit membership, so a filter case can differ."""
    return ViewDefinition(
        view_id="view-1",
        model_id="sample-service",
        view_type=ViewType.SYSTEM_CONTEXT,
        notation=Notation.C4,
        scope="system-1",
        title="System context",
        included_element_ids=("system-1",),
        layout_profile_id="layout-1",
    )


@pytest.fixture(scope="module")
def base() -> Model:
    return parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))


# -- one edit per classification ------------------------------------------------------------------


def with_field(record: object, **changes: object) -> object:
    return record.model_validate(dict(record) | changes)  # type: ignore[attr-defined]


def replacing_element(model: Model, element_id: str, **changes: object) -> Model:
    victim = next(item for item in model.elements if item.element_id == element_id)
    replaced = victim.model_validate(dict(victim) | changes)
    return model.model_validate(
        dict(model)
        | {
            "elements": tuple(
                replaced if item.element_id == element_id else item for item in model.elements
            )
        }
    )


def replacing_detail(model: Model, element_id: str, **changes: object) -> Model:
    victim = next(item for item in model.elements if item.element_id == element_id)
    detail = victim.detail
    assert detail is not None
    return replacing_element(
        model, element_id, detail=detail.model_validate(dict(detail) | changes)
    )


def replacing_relationship(model: Model, relationship_id: str, **changes: object) -> Model:
    victim = next(item for item in model.relationships if item.relationship_id == relationship_id)
    replaced = victim.model_validate(dict(victim) | changes)
    return model.model_validate(
        dict(model)
        | {
            "relationships": tuple(
                replaced if item.relationship_id == relationship_id else item
                for item in model.relationships
            )
        }
    )


def corpus(base: Model) -> Iterator[tuple[str, Model]]:
    """One candidate per classification the vocabulary can express."""
    binding = base.notation_bindings[0]
    interaction = base.interactions[0]
    reference = base.references[0]
    link = base.reference_links[0]
    schema_detail = next(i for i in base.elements if i.element_id == "schema-1").detail
    behaviour = next(i for i in base.elements if i.element_id == "process-1").detail
    assert isinstance(schema_detail, DataSchemaDetail)
    assert isinstance(behaviour, BehaviorDetail)

    # -- elements
    yield "renamed", replacing_element(base, "capability-1", name="Renamed")
    yield "retired", replacing_element(base, "capability-1", lifecycle_state=LifecycleState.RETIRED)

    yield (
        "replaced",
        replacing_element(base, "capability-1", lifecycle_state=LifecycleState.REPLACED),
    )
    yield "retyped", replacing_element(base, "capability-1", kind_id="business.process")
    yield "described", replacing_element(base, "capability-1", description="Now explained.")
    yield "aliased", replacing_element(base, "capability-1", aliases=("Portfolio Eval",))
    yield (
        "annotated",
        replacing_element(
            base,
            "capability-1",
            extensions=(Extension(namespace="soal.pilot", key="scope", value="tpo"),),
        ),
    )
    yield (
        "element added",
        base.model_validate(
            dict(base)
            | {
                "elements": (
                    *base.elements,
                    Element(
                        element_id="capability-2",
                        model_id=base.model_id,
                        kind_id="strategy.capability",
                        name="A second capability",
                    ),
                )
            }
        ),
    )
    yield (
        "element removed",
        base.model_validate(
            dict(base) | {"elements": tuple(e for e in base.elements if e.element_id != "object-1")}
        ),
    )

    # -- the five status dimensions, which DATA-29 requires stay apart
    for label, field, value in (
        ("disposition", "design_disposition", DesignDisposition.SUPERSEDED),
        ("implementation", "implementation_state", ImplementationState.DECOMMISSIONED),
        ("qualification", "technical_qualification", TechnicalQualification.QUALIFIED),
        ("acceptance", "client_acceptance", ClientAcceptance.ACCEPTED),
        ("evidence review", "evidence_review", EvidenceReview.OBSERVED),
    ):
        victim = next(i for i in base.elements if i.element_id == "system-1")
        yield (
            f"status {label}",
            replacing_element(
                base,
                "system-1",
                status=victim.status.model_validate(dict(victim.status) | {field: value}),
            ),
        )

    # -- typed detail
    yield "interface contract", replacing_detail(base, "interface-1", timeout_ms=5000)
    yield "deployment", replacing_detail(base, "deployment-1", environment="staging")
    yield (
        "requirement applicability",
        replacing_detail(base, "req-1", applicability=Applicability.NOT_APPLICABLE),
    )
    yield (
        "requirement verification",
        replacing_detail(base, "req-1", verification_method=VerificationMethod.INSPECTION),
    )
    yield (
        "schema field",
        replacing_detail(
            base,
            "schema-1",
            fields=tuple(
                f.model_validate(dict(f) | {"field_name": "renamed_field"}) if f.ordinal == 0 else f
                for f in schema_detail.fields
            ),
        ),
    )
    yield (
        "behaviour node",
        replacing_detail(
            base,
            "process-1",
            nodes=tuple(
                n.model_validate(dict(n) | {"name": "Renamed step"}) if n.ordinal == 0 else n
                for n in behaviour.nodes
            ),
        ),
    )
    yield "detail removed", replacing_element(base, "interface-1", detail=None)

    yield (
        "detail family",
        replacing_element(
            base,
            "interface-1",
            detail=DeploymentDetail(element_id="interface-1", environment="production"),
        ),
    )

    # -- relationships
    yield (
        "relationship retyped",
        replacing_relationship(base, "rel-1", relationship_type_id="composed_of"),
    )
    yield "endpoint moved", replacing_relationship(base, "rel-1", target_element_id="interface-1")
    yield "context moved", replacing_relationship(base, "rel-8", context_id="renewals")
    yield "relationship described", replacing_relationship(base, "rel-1", description="Explained.")
    yield (
        "relationship annotated",
        replacing_relationship(
            base, "rel-1", extensions=(Extension(namespace="soal.pilot", key="note", value="x"),)
        ),
    )
    yield (
        "relationship added",
        base.model_validate(
            dict(base)
            | {
                "relationships": (
                    *base.relationships,
                    Relationship(
                        relationship_id="rel-9",
                        model_id=base.model_id,
                        relationship_type_id="depends_on",
                        source_element_id="system-1",
                        target_element_id="component-1",
                    ),
                )
            }
        ),
    )
    yield (
        "relationship removed",
        base.model_validate(dict(base) | {"relationships": base.relationships[1:]}),
    )

    # -- interactions
    yield (
        "interaction renamed",
        base.model_validate(
            dict(base) | {"interactions": (with_field(interaction, name="Renamed handoff"),)}
        ),
    )
    yield (
        "participants",
        base.model_validate(
            dict(base)
            | {
                "interactions": (
                    with_field(interaction, participants=interaction.participants[:1]),
                )
            }
        ),
    )
    yield "interaction removed", base.model_validate(dict(base) | {"interactions": ()})
    yield (
        "interaction added",
        base.model_validate(
            dict(base)
            | {"interactions": (interaction, with_field(interaction, interaction_id="int-2"))}
        ),
    )

    # -- evidence
    yield (
        "reference retitled",
        base.model_validate(
            dict(base) | {"references": (with_field(reference, title="A newer title"),)}
        ),
    )
    yield (
        "reference authority",
        base.model_validate(
            dict(base) | {"references": (with_field(reference, authority="Soal Labs"),)}
        ),
    )
    yield (
        "reference removed",
        base.model_validate(dict(base) | {"references": (), "reference_links": ()}),
    )
    yield (
        "reference added",
        base.model_validate(
            dict(base) | {"references": (reference, with_field(reference, reference_id="ref-2"))}
        ),
    )
    yield (
        "link role",
        base.model_validate(
            dict(base) | {"reference_links": (with_field(link, link_role=LinkRole.QUALIFIES),)}
        ),
    )
    yield (
        "link subject",
        base.model_validate(
            dict(base)
            | {
                "reference_links": (
                    with_field(link, subject=ElementReference(element_id="system-1")),
                )
            }
        ),
    )
    yield "link removed", base.model_validate(dict(base) | {"reference_links": ()})
    yield (
        "link added",
        base.model_validate(
            dict(base) | {"reference_links": (link, with_field(link, link_id="link-2"))}
        ),
    )
    yield (
        "link noted",
        base.model_validate(
            dict(base) | {"reference_links": (with_field(link, note="Because of D-030."),)}
        ),
    )

    # -- notation and view
    yield (
        "notation mapping",
        base.model_validate(
            dict(base)
            | {"notation_bindings": (with_field(binding, mapping_profile_version="2.0.0"),)}
        ),
    )
    yield (
        "binding resubjected",
        base.model_validate(
            dict(base)
            | {
                "notation_bindings": (
                    with_field(binding, subject=ElementReference(element_id="system-1")),
                )
            }
        ),
    )
    yield (
        "view membership",
        base.model_validate(
            dict(base) | {"notation_bindings": (with_field(binding, view_id="view-1"),)}
        ),
    )
    yield (
        "layout link",
        base.model_validate(
            dict(base)
            | {"notation_bindings": (with_field(binding, link_target="diagrams/a.svg#x"),)}
        ),
    )
    yield (
        "projection provenance",
        base.model_validate(
            dict(base)
            | {"notation_bindings": (with_field(binding, projection_artifact_id="art-1"),)}
        ),
    )
    yield "binding removed", base.model_validate(dict(base) | {"notation_bindings": ()})
    yield (
        "binding added",
        base.model_validate(
            dict(base)
            | {"notation_bindings": (binding, with_field(binding, binding_id="binding-2"))}
        ),
    )

    # -- model level
    yield "profile version", base.model_validate(dict(base) | {"profile_version": "2.0.0"})
    yield "schema version", base.model_validate(dict(base) | {"schema_version": "1.1.0"})


def reversed_corpus(base: Model) -> Iterator[tuple[str, Model, Model]]:
    """The two cases that only exist backwards.

    A detail arriving and an element being reactivated are the *other* direction of a case already
    in the corpus. Running the corpus forwards only would leave both undemonstrated, and inventing
    a second fixture to hold "an interface with no detail" would be a fixture nobody reads.
    """
    stripped = replacing_element(base, "interface-1", detail=None)
    yield "detail added", stripped, base
    retired = replacing_element(base, "capability-1", lifecycle_state=LifecycleState.RETIRED)
    yield "reactivated", retired, base


def view_corpus(base: Model) -> Iterator[tuple[str, Model, Model]]:
    """Every view case, against a baseline that already has a view.

    Separate from `corpus` because those cases all compare against the example, which declares no
    view — so an edited view would read as a view *added* and nine kinds would go undemonstrated
    while the suite passed. The example stays free of a record it does not otherwise need, and
    `view added` and `view removed` fall out as the two ends of this same pair.
    """
    with_view = base.model_validate(dict(base) | {"views": (_view(),)})
    yield "view added", base, with_view
    yield "view removed", with_view, base

    for label, changes in (
        ("view retyped", {"view_type": ViewType.SYSTEM_LANDSCAPE}),
        (
            "view renotated",
            {"notation": Notation.ARCHIMATE, "view_type": ViewType.ARCHIMATE_LAYERED},
        ),
        ("view rescoped", {"scope": "component-1"}),
        ("view metadata", {"title": "Renamed view"}),
        ("view membership", {"included_element_ids": ("system-1", "component-1")}),
        ("view membership policy", {"membership_policy": MembershipPolicy.INDUCED}),
        ("view perspective", {"perspective": "ownership"}),
        (
            "view filter",
            {
                "membership_policy": MembershipPolicy.DERIVED,
                "filter": (
                    ViewFilter(
                        filter_mode=FilterMode.INCLUDE,
                        dimension=FilterDimension.KIND,
                        values=("software.system",),
                    ),
                ),
            },
        ),
        ("view layout profile", {"layout_profile_id": "layout-2"}),
        ("view publication", {"publication_state": PublicationState.PUBLISHED}),
    ):
        edited = with_view.model_validate(
            dict(with_view) | {"views": (with_field(_view(), **changes),)}
        )
        yield label, with_view, edited


def pairs(base: Model) -> Iterator[tuple[str, Model, Model]]:
    """Every case, as the pair of models it compares."""
    for label, candidate in corpus(base):
        yield label, base, candidate
    yield from reversed_corpus(base)
    yield from view_corpus(base)


def observed(base: Model) -> dict[ChangeKind, str]:
    """Every kind the differ emits over the corpus, and the case that first produced it."""
    seen: dict[ChangeKind, str] = {}
    for label, before, after in pairs(base):
        for kind in model_changes(before, after).kinds:
            seen.setdefault(kind, label)
    return seen


# -- the guard ------------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.qualification
@pytest.mark.requirement("DATA-26")
def test_every_declared_kind_is_produced_by_something(base: Model) -> None:
    """Membership in the table is not production. This is the half that was missing.

    The allow-list holds only the kinds that are structurally unemittable — each classifies a field
    so it cannot hide in an exclusion set, and `NEVER_EMITTED` is the same set from the other
    direction. Anything else that lands here is a kind nobody can demonstrate.
    """
    seen = observed(base)

    assert seen, "the corpus produced no changes at all"
    undemonstrated = set(ChangeKind) - set(seen) - NEVER_EMITTED
    assert not undemonstrated, (
        f"declared but produced by nothing: {sorted(k.value for k in undemonstrated)}. "
        f"Add a case to the corpus, or explain why the kind cannot be reached."
    )


@pytest.mark.integration
@pytest.mark.requirement("DATA-26")
def test_the_differ_never_emits_a_kind_declared_unemittable(base: Model) -> None:
    """The assertion `NEVER_EMITTED`'s own docstring claimed and no test made.

    Five kinds exist so their fields are classified rather than hidden in an exclusion set. Before
    this the only assertions about them were set algebra over two frozen constants, which would
    have passed with a differ that returned nothing for every input.
    """
    assert not set(observed(base)) & NEVER_EMITTED


@pytest.mark.integration
@pytest.mark.requirement("DATA-26")
def test_each_category_data_26_names_is_produced_by_the_case_that_should_produce_it(
    base: Model,
) -> None:
    """Section 6's list, one row at a time, against what the differ actually emits.

    Three of these had no test at all, and `relationship_endpoint_changed` is the one the
    classification table introduces as the case the W5 graph comparison reports as *no change*.
    """
    by_case = {label: model_changes(before, after).kinds for label, before, after in pairs(base)}

    assert ChangeKind.ELEMENT_ADDED in by_case["element added"]
    assert ChangeKind.ELEMENT_RETIRED in by_case["retired"]
    assert ChangeKind.ELEMENT_RENAMED in by_case["renamed"]
    assert ChangeKind.RELATIONSHIP_ADDED in by_case["relationship added"]
    assert ChangeKind.RELATIONSHIP_REMOVED in by_case["relationship removed"]
    assert ChangeKind.RELATIONSHIP_ENDPOINT_CHANGED in by_case["endpoint moved"]
    assert ChangeKind.INTERFACE_CONTRACT_CHANGED in by_case["interface contract"]
    assert ChangeKind.REQUIREMENT_APPLICABILITY_CHANGED in by_case["requirement applicability"]
    assert ChangeKind.QUALIFICATION_CHANGED in by_case["status qualification"]
    assert ChangeKind.EVIDENCE_CHANGED in by_case["reference retitled"]
    assert ChangeKind.VIEW_MEMBERSHIP_CHANGED in by_case["view membership"]
    assert ChangeKind.LAYOUT_LINK_CHANGED in by_case["layout link"]


@pytest.mark.integration
@pytest.mark.requirement("DATA-26", "DATA-31")
def test_only_the_presentation_cases_stay_out_of_the_narrative(base: Model) -> None:
    """The gate, across the whole corpus rather than on the four qualification cases.

    Every case either belongs in the narrative or does not, and the ones that do not are exactly
    the ones a reader would call presentation. Asserting the partition over fifty cases is what
    turns the gate from a claim about `link_target` into a claim about the classification.
    """
    presentation_only = {
        label for label, before, after in pairs(base) if not model_changes(before, after).narrative
    }

    assert presentation_only == {
        "aliased",
        "layout link",
        "projection provenance",
        # W7a's fourth member, and the first one that is a *layout* change rather than a
        # renderer-provenance one. `ViewDefinition.layout_profile_id` is the only `LAYOUT_ONLY`
        # field reachable from `Model`, so this is the wave's hard gate — "a layout-only change
        # produces no semantic diff" — demonstrated from inside the canonical model rather than
        # argued from the classification table. Changing which profile lays a view out moves the
        # model digest and produces no narrative record at all.
        "view layout profile",
    }


@pytest.mark.integration
@pytest.mark.requirement("DATA-26", "DATA-31")
def test_every_case_lands_in_exactly_one_of_narrative_and_presentation(base: Model) -> None:
    """`narrative` and `presentation` are complementary filters and nothing asserted they partition.

    A record falling out of both would be invisible to the gate while still being reported under
    `--include-presentation`; one falling into both would be counted twice.
    """
    for label, before, after in pairs(base):
        changes = model_changes(before, after)
        narrative = {(r.collection, r.identity) for r in changes.narrative}
        presentation = {(r.collection, r.identity) for r in changes.presentation}
        every = {(r.collection, r.identity) for r in changes.records}

        assert narrative | presentation == every, label
        assert not (narrative & presentation), label


@pytest.mark.integration
@pytest.mark.requirement("DATA-26", "DATA-31")
def test_every_reachable_nature_is_produced_and_the_reserved_ones_are_not(base: Model) -> None:
    """The reservation, checked against data rather than against the table."""
    natures = {
        record.natures[0] if len(record.natures) == 1 else nature
        for _, before, after in pairs(base)
        for record in model_changes(before, after).records
        for nature in record.natures
    }

    assert ChangeNature.CANONICAL_SEMANTIC in natures
    assert ChangeNature.NOTATION_MAPPING in natures
    assert ChangeNature.VIEW_MEMBERSHIP in natures
    assert ChangeNature.LAYOUT_ONLY in natures
    assert ChangeNature.RENDERER_TOOLCHAIN in natures
    assert ChangeNature.STYLE_THEME_ONLY not in natures
    assert ChangeNature.PUBLICATION_NAVIGATION_ONLY not in natures
