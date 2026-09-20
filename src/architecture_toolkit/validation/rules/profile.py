"""Release and profile rules (CORE-07).

Reduced in W1 to the one check the available models support. Release coherence needs W4's
manifest; view membership needs W7a's view definitions and is recorded as a deferral in
`rules/__init__.py` rather than being silently absent.
"""

from collections.abc import Iterable

from architecture_toolkit.validation.candidate import Candidate
from architecture_toolkit.validation.context import ValidationContext
from architecture_toolkit.validation.diagnostics import Diagnostic, build_diagnostic
from architecture_toolkit.validation.rules import RuleFamily, rule


@rule(
    rule_id="profile-version-supported",
    family=RuleFamily.RELEASES,
    emits={"CORE.RELEASE.PROFILE_VERSION_UNSUPPORTED"},
    requirements={"CORE-06", "CORE-07"},
    summary="The model's declared profile version matches the profile it is validated against.",
)
def profile_version_supported(
    candidate: Candidate, context: ValidationContext
) -> Iterable[Diagnostic]:
    """Uses the context, which is the point: CORE-06 requires validation be explicit about this.

    A model authored against one vocabulary and validated against another can pass every
    structural rule and still mean something different.
    """
    declared = candidate.model.profile_version
    available = candidate.profile.profile_version
    if declared != available or declared != context.profile_version:
        yield build_diagnostic(
            "CORE.RELEASE.PROFILE_VERSION_UNSUPPORTED",
            message=(
                f"model declares profile version {declared!r}; profile "
                f"{candidate.profile.profile_id!r} provides {available!r} and the validation "
                f"context names {context.profile_version!r}."
            ),
            rule_id="profile-version-supported",
            canonical_object_id=candidate.model.model_id,
        )
