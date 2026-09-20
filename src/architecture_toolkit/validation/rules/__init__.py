"""Cross-record validation rules (CORE-07).

core.md names eight rule families. All eight are declared here, including the three that cannot
be implemented yet, because a family that is simply absent is indistinguishable from one nobody
thought of. A family with no rules carries a `Deferral` naming the wave that unblocks it, and a
test asserts that correspondence in both directions.

Rules are pure with respect to the candidate. They return diagnostics; they never mutate, and
they never raise for a problem in the model — a raise is a toolkit defect, and the runner
converts it into `CORE.SCHEMA.RULE_CRASHED` so one broken rule cannot take down a report.

Registration carries the evidence requirements with it. A rule declares the codes it may emit and
the requirement IDs it evidences, and three guards in `tests/unit/test_rules.py` make a rule
without evidence impossible to land: every declared code must be registered, every requirement ID
must exist in `reference/requirements.json`, and every rule must have both a passing and a
failing case.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from architecture_toolkit.domain.identifiers import RuleId
from architecture_toolkit.validation.candidate import Candidate
from architecture_toolkit.validation.codes import CODES
from architecture_toolkit.validation.context import ValidationContext
from architecture_toolkit.validation.diagnostics import Diagnostic, build_diagnostic

__all__ = [
    "DEFERRALS",
    "REGISTRY",
    "Deferral",
    "Rule",
    "RuleFamily",
    "RuleSpec",
    "rule",
    "run_all",
]

Rule = Callable[[Candidate, ValidationContext], Iterable[Diagnostic]]


class RuleFamily(StrEnum):
    """The eight families core.md enumerates, verbatim and in order."""

    IDENTITY = "identity"
    ENDPOINTS = "endpoints"
    CONTAINMENT = "containment"
    EVIDENCE = "evidence"
    INTERFACES = "interfaces"
    WORKFLOWS = "workflows"
    VIEWS = "views"
    RELEASES = "releases"


@dataclass(frozen=True, slots=True)
class Deferral:
    wave: str
    blocked_on: str
    reason: str


DEFERRALS: Mapping[RuleFamily, Deferral] = {
    RuleFamily.VIEWS: Deferral(
        wave="W7a",
        blocked_on="PROJ-02, PROJ-03",
        reason="No view definition exists to check membership against.",
    ),
}
"""Families that cannot be implemented in W1, with what unblocks them.

`WORKFLOWS` and `RELEASES` are reduced rather than deferred — each has the one rule its W1
models support — so neither appears here. Only `VIEWS` has nothing at all to check.
"""


@dataclass(frozen=True, slots=True)
class RuleSpec:
    rule_id: RuleId
    family: RuleFamily
    emits: frozenset[str]
    requirements: frozenset[str]
    summary: str
    fn: Rule


REGISTRY: dict[RuleId, RuleSpec] = {}


def rule(
    *,
    rule_id: RuleId,
    family: RuleFamily,
    emits: Iterable[str],
    requirements: Iterable[str],
    summary: str,
) -> Callable[[Rule], Rule]:
    """Register a rule, refusing at import time if it declares an unregistered code."""

    def register(fn: Rule) -> Rule:
        declared = frozenset(emits)
        unknown = sorted(declared - set(CODES))
        if unknown:
            message = f"rule {rule_id!r} declares unregistered codes: {unknown}"
            raise ValueError(message)
        if rule_id in REGISTRY:
            message = f"duplicate rule id {rule_id!r}"
            raise ValueError(message)
        REGISTRY[rule_id] = RuleSpec(
            rule_id=rule_id,
            family=family,
            emits=declared,
            requirements=frozenset(requirements),
            summary=summary,
            fn=fn,
        )
        return fn

    return register


def run_all(candidate: Candidate, context: ValidationContext) -> tuple[Diagnostic, ...]:
    """Run every registered rule in a deterministic order.

    A rule that raises yields `CORE.SCHEMA.RULE_CRASHED` rather than propagating: a defect in one
    rule must not deny the reader every other finding in the report.
    """
    produced: list[Diagnostic] = []
    for rule_id in sorted(REGISTRY):
        spec = REGISTRY[rule_id]
        try:
            emitted = tuple(spec.fn(candidate, context))
        except Exception as failure:
            produced.append(
                build_diagnostic(
                    "CORE.SCHEMA.RULE_CRASHED",
                    message=f"rule {rule_id!r} raised {type(failure).__name__}: {failure}",
                    rule_id=rule_id,
                )
            )
            continue
        undeclared = sorted({d.code for d in emitted} - spec.emits)
        if undeclared:
            produced.append(
                build_diagnostic(
                    "CORE.SCHEMA.RULE_CRASHED",
                    message=f"rule {rule_id!r} emitted undeclared codes: {undeclared}",
                    rule_id=rule_id,
                )
            )
            continue
        produced.extend(emitted)
    return tuple(produced)
