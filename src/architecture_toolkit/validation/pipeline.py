"""Compose record validation with cross-record validation (CORE-06, CORE-07, CORE-10).

core.md's flow is `validated baseline + commands -> candidate construction -> complete Pydantic
validation -> cross-record validation -> immutable candidate`. It spans two packages, and this
module is why that does not invert the layering: composing it in `domain/` would make the domain
import `validation/`, so `validation/` composes instead and the runtime dependency stays
one-way.

The only edge in the other direction is a `TYPE_CHECKING` import in `domain/protocols.py`, which
gives `ValidatorAdapter` its real signature without importing anything at runtime. Protocols are
structural, so nothing is needed at runtime for conformance to hold.
"""

from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.registry import BASELINE_PROFILE, Profile
from architecture_toolkit.validation.candidate import Candidate
from architecture_toolkit.validation.claims import (
    ClaimOutcome,
    ClaimStatus,
    ValidationClaimReport,
)
from architecture_toolkit.validation.context import ValidationContext
from architecture_toolkit.validation.diagnostics import Diagnostic
from architecture_toolkit.validation.rules import DEFERRALS, REGISTRY, RuleFamily, run_all
from architecture_toolkit.validation.taxonomy import ValidationClaim

# Importing the rule modules is what registers them. Explicit rather than a package scan: a rule
# that is not imported does not run, and a scan would hide that behind a filesystem question.
from architecture_toolkit.validation.rules import (  # isort: skip
    profile as _profile_rules,
    semantic as _semantic_rules,
    structural as _structural_rules,
)

__all__ = ["CrossRecordValidator", "validate_model"]

_ = (_structural_rules, _semantic_rules, _profile_rules)

# Which rule families speak to which claim. Written down so the claim block in a report is
# derived from what ran rather than asserted alongside it.
_CLAIM_FAMILIES: dict[ValidationClaim, frozenset[RuleFamily]] = {
    ValidationClaim.CANONICAL_STRUCTURE: frozenset({RuleFamily.IDENTITY}),
    ValidationClaim.CROSS_MODEL_SEMANTICS: frozenset(
        {
            RuleFamily.ENDPOINTS,
            RuleFamily.CONTAINMENT,
            RuleFamily.EVIDENCE,
            RuleFamily.INTERFACES,
            RuleFamily.WORKFLOWS,
            RuleFamily.VIEWS,
            RuleFamily.RELEASES,
        }
    ),
}

_UNREACHABLE: dict[ValidationClaim, tuple[ClaimStatus, str]] = {
    ValidationClaim.NOTATION_SEMANTICS: (
        ClaimStatus.NOT_CHECKED,
        "no notation is generated before W7b, so nothing has been mapped to check",
    ),
    ValidationClaim.SCHEMA_SYNTAX: (
        ClaimStatus.NOT_CHECKED,
        "Pydantic is authoritative at runtime; the generated JSON Schema is an exported "
        "contract, and its agreement with Pydantic is proven once in scripts/check_schema.py",
    ),
    ValidationClaim.RENDERER: (
        ClaimStatus.NOT_IMPLEMENTED,
        "no renderer exists before W7b",
    ),
    ValidationClaim.REAL_WORLD_CORRECTNESS: (
        ClaimStatus.NOT_ESTABLISHED,
        "no tool run establishes this, and none ever will",
    ),
}


def _outcome(claim: ValidationClaim, diagnostics: tuple[Diagnostic, ...]) -> ClaimOutcome:
    if claim in _UNREACHABLE:
        status, scope = _UNREACHABLE[claim]
        return ClaimOutcome(claim=claim, status=status, scope=scope, checked_by=())

    families = _CLAIM_FAMILIES[claim]
    ran = tuple(sorted(spec.rule_id for spec in REGISTRY.values() if spec.family in families))
    deferred = sorted(family.value for family in families if family in DEFERRALS)
    found = tuple(d for d in diagnostics if d.claim is claim)
    failing = [d for d in found if d.severity.value == "error"]

    if failing:
        status = ClaimStatus.FAILED
    elif deferred:
        status = ClaimStatus.NOT_FULLY_CHECKED
    else:
        status = ClaimStatus.PASSED

    scope = f"{len(ran)} rule(s) ran"
    if deferred:
        scope += f"; {', '.join(deferred)} deferred"
    return ClaimOutcome(
        claim=claim,
        status=status,
        scope=scope,
        checked_by=ran,
        diagnostic_count=len(found),
    )


def validate_model(
    model: Model,
    *,
    profile: Profile = BASELINE_PROFILE,
    context: ValidationContext | None = None,
) -> ValidationClaimReport:
    """Run every registered rule and report what was and was not established."""
    resolved = context or ValidationContext(
        schema_version=model.schema_version, profile_version=profile.profile_version
    )
    candidate = Candidate(model=model, profile=profile)
    diagnostics = run_all(candidate, resolved)
    return ValidationClaimReport(
        model_id=model.model_id,
        schema_version=model.schema_version,
        profile_version=model.profile_version,
        validation_mode=resolved.validation_mode,
        claims=tuple(_outcome(claim, diagnostics) for claim in ValidationClaim),
        diagnostics=diagnostics,
    )


class CrossRecordValidator:
    """The concrete `ValidatorAdapter` (CORE-58). Pure with respect to the candidate."""

    def __init__(self, profile: Profile = BASELINE_PROFILE) -> None:
        self._profile = profile

    def validate(self, candidate: Model, *, context: ValidationContext) -> tuple[Diagnostic, ...]:
        return run_all(Candidate(model=candidate, profile=self._profile), context)
