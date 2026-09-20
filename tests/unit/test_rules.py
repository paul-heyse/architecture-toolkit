"""The cross-record rule layer (CORE-06, CORE-07)."""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.registry import BASELINE_PROFILE
from architecture_toolkit.validation.candidate import Candidate
from architecture_toolkit.validation.codes import CODES
from architecture_toolkit.validation.context import ValidationContext
from architecture_toolkit.validation.diagnostics import Diagnostic
from architecture_toolkit.validation.pipeline import validate_model
from architecture_toolkit.validation.rules import DEFERRALS, REGISTRY, RuleFamily, run_all

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = ValidationContext(schema_version="1.0.0", profile_version="1.0.0")


def _known_requirements() -> frozenset[str]:
    index = json.loads((ROOT / "reference" / "requirements.json").read_text())
    return frozenset(entry["id"] for entry in index["requirements"])


def _check(source: dict[str, Any]) -> tuple[Diagnostic, ...]:
    model = Model.model_validate_json(json.dumps(source))
    return run_all(Candidate(model=model, profile=BASELINE_PROFILE), CONTEXT)


@pytest.mark.unit
@pytest.mark.requirement("CORE-07")
def test_all_eight_families_are_declared_and_the_empty_ones_say_why() -> None:
    """A family that is simply absent is indistinguishable from one nobody thought of."""
    assert len(RuleFamily) == 8
    populated = {spec.family for spec in REGISTRY.values()}
    for family in RuleFamily:
        assert family in populated or family in DEFERRALS, family
    for family, deferral in DEFERRALS.items():
        assert family not in populated, f"{family} has rules and a deferral"
        assert deferral.wave
        assert deferral.blocked_on
        assert deferral.reason


@pytest.mark.unit
@pytest.mark.requirement("CORE-07")
def test_every_rule_declares_registered_codes_and_real_requirements() -> None:
    known = _known_requirements()
    for spec in REGISTRY.values():
        assert spec.emits, f"{spec.rule_id} emits nothing"
        assert spec.emits <= set(CODES), spec.rule_id
        assert spec.requirements, f"{spec.rule_id} evidences nothing"
        assert spec.requirements <= known, f"{spec.rule_id} names unknown requirement IDs"


def _element(element_id: str, kind_id: str = "software.component", **extra: Any) -> dict[str, Any]:
    return {
        "element_id": element_id,
        "model_id": "m-1",
        "kind_id": kind_id,
        "name": element_id.upper(),
        **extra,
    }


def _relation(rel: str, kind: str, source: str, target: str) -> dict[str, Any]:
    return {
        "relationship_id": rel,
        "model_id": "m-1",
        "relationship_type_id": kind,
        "source_element_id": source,
        "target_element_id": target,
    }


# One payload per rule, each of which that rule must catch. `docs/contract-enforcement.md` states
# the standing convention — "every guard asserts a known-bad input is caught, not only that the
# current tree is clean" — and this is that convention applied to validation rules. The totality
# test below makes a rule without a fixture impossible to land.
TRIGGERS: dict[str, dict[str, Any]] = {
    "unique-identities": {
        "model_id": "m-1",
        "elements": [_element("dup-1"), _element("dup-1")],
    },
    "endpoints-resolve": {
        "model_id": "m-1",
        "elements": [_element("a-1", "software.system")],
        "relationships": [_relation("rel-1", "contains", "a-1", "ghost")],
    },
    "endpoint-kinds": {
        "model_id": "m-1",
        "elements": [
            _element("role-1", "organization.role"),
            _element("req-1", "motivation.requirement"),
        ],
        "relationships": [_relation("rel-1", "contains", "role-1", "req-1")],
    },
    "no-self-loop": {
        "model_id": "m-1",
        "elements": [_element("a-1", "software.system")],
        "relationships": [_relation("rel-1", "exchanges_data_with", "a-1", "a-1")],
    },
    "no-duplicate-inverse": {
        "model_id": "m-1",
        "elements": [_element("a-1", "software.system"), _element("b-1", "software.system")],
        "relationships": [
            _relation("rel-1", "exchanges_data_with", "a-1", "b-1"),
            _relation("rel-2", "exchanges_data_with", "b-1", "a-1"),
        ],
    },
    "acyclic": {
        "model_id": "m-1",
        "elements": [_element(f"c-{n}") for n in (1, 2, 3)],
        "relationships": [
            _relation(f"rel-{n}", "contains", f"c-{n}", f"c-{n % 3 + 1}") for n in (1, 2, 3)
        ],
    },
    "single-parent": {
        "model_id": "m-1",
        "elements": [_element(f"c-{n}") for n in (1, 2, 3)],
        "relationships": [
            _relation("rel-a", "contains", "c-1", "c-3"),
            _relation("rel-b", "contains", "c-2", "c-3"),
        ],
    },
    "reference-links-resolve": {
        "model_id": "m-1",
        "reference_links": [
            {
                "link_id": "link-1",
                "model_id": "m-1",
                "reference_id": "ghost-ref",
                "subject": {"subject_kind": "element", "element_id": "ghost-element"},
                "link_role": "supports",
            }
        ],
    },
    "contradicted-evidence-needs-review": {
        "model_id": "m-1",
        "elements": [_element("a-1")],
        "references": [
            {
                "reference_id": "ref-1",
                "model_id": "m-1",
                "reference_kind": "document",
                "title": "Disagreeing source",
            }
        ],
        "reference_links": [
            {
                "link_id": "link-1",
                "model_id": "m-1",
                "reference_id": "ref-1",
                "subject": {"subject_kind": "element", "element_id": "a-1"},
                "link_role": "contradicts",
            }
        ],
    },
    "detail-family-permitted": {
        "model_id": "m-1",
        "elements": [
            _element(
                "sys-1",
                "software.system",
                detail={
                    "detail_family": "interface",
                    "element_id": "sys-1",
                    "transport": {
                        "protocol": "https",
                        "interaction_mode": "synchronous",
                        "serialization": "json",
                    },
                },
            )
        ],
    },
    "schema-references-resolve": {
        "model_id": "m-1",
        "elements": [
            _element(
                "iface-1",
                "software.interface",
                detail={
                    "detail_family": "interface",
                    "element_id": "iface-1",
                    "transport": {
                        "protocol": "https",
                        "interaction_mode": "synchronous",
                        "serialization": "json",
                    },
                    "request_schema_id": "ghost-schema",
                },
            )
        ],
    },
    "workflow-participants": {
        "model_id": "m-1",
        "elements": [
            _element(
                "proc-1",
                "business.process",
                detail={
                    "detail_family": "behavior",
                    "element_id": "proc-1",
                    "nodes": [
                        {
                            "node_id": "n1",
                            "node_type": "task",
                            "name": "Work",
                            "ordinal": 0,
                            "participant_element_id": "ghost",
                        }
                    ],
                },
            )
        ],
    },
    "profile-version-supported": {"model_id": "m-1", "profile_version": "2.0.0"},
}


@pytest.mark.unit
@pytest.mark.requirement("CORE-07")
def test_every_registered_rule_has_a_triggering_fixture() -> None:
    """A rule nothing can trigger is a rule nobody has shown to work."""
    missing = sorted(set(REGISTRY) - set(TRIGGERS))
    assert not missing, f"rules with no known-bad fixture: {missing}"
    stale = sorted(set(TRIGGERS) - set(REGISTRY))
    assert not stale, f"fixtures for rules that no longer exist: {stale}"


@pytest.mark.unit
@pytest.mark.requirement("CORE-07")
@pytest.mark.parametrize("rule_id", sorted(TRIGGERS))
def test_each_rule_catches_its_known_bad_input(rule_id: str) -> None:
    fired = {diagnostic.rule_id for diagnostic in _check(TRIGGERS[rule_id])}
    assert rule_id in fired, f"{rule_id} did not fire on its own fixture"


@pytest.mark.unit
@pytest.mark.requirement("CORE-07")
def test_no_rule_fires_on_a_clean_model(minimal_model_source: dict[str, Any]) -> None:
    """The other half. A rule that fires on everything catches nothing."""
    produced = _check(minimal_model_source)
    assert {d.code for d in produced} == {"CORE.WORKFLOW.NO_PARTICIPANT"}


@pytest.mark.unit
@pytest.mark.requirement("CORE-07")
def test_every_relationship_type_rule_id_in_the_registry_is_a_real_rule() -> None:
    """Closes the loop the registry opened in the previous change.

    `RelationshipTypeDefinition.validation_rule_ids` was declared before any rule existed. A
    dangling id there would mean a profile believes a constraint is enforced when nothing
    enforces it.
    """
    declared: set[str] = set()
    for entry in BASELINE_PROFILE.relationship_types:
        declared |= set(entry.validation_rule_ids)
    assert declared <= set(REGISTRY), sorted(declared - set(REGISTRY))


@pytest.mark.unit
@pytest.mark.requirement("CORE-07")
def test_rules_do_not_mutate_the_candidate(minimal_model_source: dict[str, Any]) -> None:
    """Purity, using the hashability guard a second time."""
    model = Model.model_validate_json(json.dumps(minimal_model_source))
    candidate = Candidate(model=model, profile=BASELINE_PROFILE)
    before = hash(candidate)
    first = run_all(candidate, CONTEXT)
    assert hash(candidate) == before
    assert run_all(candidate, CONTEXT) == first


@pytest.mark.unit
@pytest.mark.requirement("CORE-07")
def test_a_crashing_rule_does_not_deny_the_reader_every_other_finding() -> None:
    from architecture_toolkit.validation.rules import RuleSpec

    def explode(candidate: Candidate, context: ValidationContext) -> Iterable[Diagnostic]:
        del candidate, context
        raise RuntimeError("deliberate")

    REGISTRY["zzz-deliberate-crash"] = RuleSpec(
        rule_id="zzz-deliberate-crash",
        family=RuleFamily.IDENTITY,
        emits=frozenset({"CORE.DOMAIN.DUPLICATE_ID"}),
        requirements=frozenset({"CORE-07"}),
        summary="A deliberately broken rule.",
        fn=explode,
    )
    try:
        produced = _check({"model_id": "m-1", "elements": [], "relationships": []})
    finally:
        del REGISTRY["zzz-deliberate-crash"]
    crashed = [d for d in produced if d.code == "CORE.SCHEMA.RULE_CRASHED"]
    assert len(crashed) == 1
    assert "deliberate" in crashed[0].message


@pytest.mark.unit
@pytest.mark.requirement("CORE-07", "DATA-03")
def test_endpoints_resolve_reports_the_relationship_and_the_side() -> None:
    produced = _check(
        {
            "model_id": "m-1",
            "elements": [
                {
                    "element_id": "a-1",
                    "model_id": "m-1",
                    "kind_id": "software.system",
                    "name": "A",
                }
            ],
            "relationships": [
                {
                    "relationship_id": "rel-1",
                    "model_id": "m-1",
                    "relationship_type_id": "contains",
                    "source_element_id": "a-1",
                    "target_element_id": "ghost",
                }
            ],
        }
    )
    unresolved = [d for d in produced if d.code == "CORE.RELATION.UNRESOLVED_ENDPOINT"]
    assert len(unresolved) == 1
    assert unresolved[0].relationship_id == "rel-1"
    assert unresolved[0].field_path == "relationships.rel-1.target_element_id"


@pytest.mark.unit
@pytest.mark.requirement("CORE-07", "DATA-05")
def test_endpoint_kinds_rejects_an_impermissible_pairing() -> None:
    """The check the seven-member enum could never make."""
    produced = _check(
        {
            "model_id": "m-1",
            "elements": [
                {
                    "element_id": "req-1",
                    "model_id": "m-1",
                    "kind_id": "motivation.requirement",
                    "name": "R",
                },
                {
                    "element_id": "role-1",
                    "model_id": "m-1",
                    "kind_id": "organization.role",
                    "name": "Role",
                },
            ],
            "relationships": [
                {
                    "relationship_id": "rel-1",
                    "model_id": "m-1",
                    "relationship_type_id": "contains",
                    "source_element_id": "role-1",
                    "target_element_id": "req-1",
                }
            ],
        }
    )
    codes = {d.code for d in produced}
    assert "CORE.RELATION.ENDPOINT_KIND_NOT_PERMITTED" in codes


@pytest.mark.unit
@pytest.mark.requirement("CORE-07", "DATA-06")
def test_no_duplicate_inverse_catches_a_mirrored_symmetric_relationship() -> None:
    base = {
        "model_id": "m-1",
        "elements": [
            {"element_id": "a-1", "model_id": "m-1", "kind_id": "software.system", "name": "A"},
            {"element_id": "b-1", "model_id": "m-1", "kind_id": "software.system", "name": "B"},
        ],
        "relationships": [
            {
                "relationship_id": "rel-1",
                "model_id": "m-1",
                "relationship_type_id": "exchanges_data_with",
                "source_element_id": "a-1",
                "target_element_id": "b-1",
            },
            {
                "relationship_id": "rel-2",
                "model_id": "m-1",
                "relationship_type_id": "exchanges_data_with",
                "source_element_id": "b-1",
                "target_element_id": "a-1",
            },
        ],
    }
    codes = {d.code for d in _check(base)}
    assert "CORE.RELATION.DUPLICATE_INVERSE" in codes


@pytest.mark.unit
@pytest.mark.requirement("CORE-07", "DATA-05")
def test_acyclic_and_single_parent_catch_their_own_shapes() -> None:
    elements = [
        {"element_id": f"c-{n}", "model_id": "m-1", "kind_id": "software.component", "name": "C"}
        for n in (1, 2, 3)
    ]
    cycle = {
        "model_id": "m-1",
        "elements": elements,
        "relationships": [
            {
                "relationship_id": f"rel-{n}",
                "model_id": "m-1",
                "relationship_type_id": "contains",
                "source_element_id": f"c-{n}",
                "target_element_id": f"c-{n % 3 + 1}",
            }
            for n in (1, 2, 3)
        ],
    }
    assert "CORE.CONTAINMENT.CYCLE" in {d.code for d in _check(cycle)}

    two_parents = {
        "model_id": "m-1",
        "elements": elements,
        "relationships": [
            {
                "relationship_id": "rel-a",
                "model_id": "m-1",
                "relationship_type_id": "contains",
                "source_element_id": "c-1",
                "target_element_id": "c-3",
            },
            {
                "relationship_id": "rel-b",
                "model_id": "m-1",
                "relationship_type_id": "contains",
                "source_element_id": "c-2",
                "target_element_id": "c-3",
            },
        ],
    }
    assert "CORE.CONTAINMENT.MULTIPLE_PARENTS" in {d.code for d in _check(two_parents)}


@pytest.mark.unit
@pytest.mark.requirement("CORE-07", "DATA-09")
def test_reference_links_resolve_reports_both_halves() -> None:
    produced = _check(
        {
            "model_id": "m-1",
            "elements": [],
            "reference_links": [
                {
                    "link_id": "link-1",
                    "model_id": "m-1",
                    "reference_id": "ghost-ref",
                    "subject": {"subject_kind": "element", "element_id": "ghost-element"},
                    "link_role": "supports",
                }
            ],
        }
    )
    codes = {d.code for d in produced}
    assert "CORE.EVIDENCE.UNRESOLVED_REFERENCE" in codes
    assert "CORE.EVIDENCE.UNRESOLVED_SUBJECT" in codes


@pytest.mark.unit
@pytest.mark.requirement("CORE-07", "DATA-41")
def test_a_manual_step_is_reported_as_a_gap_and_never_fails(
    minimal_model_source: dict[str, Any],
) -> None:
    """DATA-41, operationally.

    The example's approval step has no application behind it. That must appear in the report and
    must not fail the run — if gaps failed, authors would invent values to make CI green, which
    is exactly what the requirement forbids.
    """
    model = Model.model_validate_json(json.dumps(minimal_model_source))
    report = validate_model(model)
    gaps = report.evidence_gaps
    assert [d.code for d in gaps] == ["CORE.WORKFLOW.NO_PARTICIPANT"]
    assert not report.hard_errors


@pytest.mark.unit
@pytest.mark.requirement("CORE-06")
def test_profile_version_supported_uses_the_validation_context() -> None:
    """CORE-06's context is not decorative: this rule reads it and changes answer."""
    model = Model.model_validate_json(
        json.dumps({"model_id": "m-1", "profile_version": "2.0.0", "elements": []})
    )
    mismatched = run_all(Candidate(model=model, profile=BASELINE_PROFILE), CONTEXT)
    assert "CORE.RELEASE.PROFILE_VERSION_UNSUPPORTED" in {d.code for d in mismatched}
