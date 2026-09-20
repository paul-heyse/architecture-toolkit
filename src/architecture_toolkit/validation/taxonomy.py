"""Three orthogonal axes for classifying a diagnostic (CORE-07, DATA-31, PROJ-07).

The contracts carry three different enumerations and it is tempting to read them as three
attempts at one list. They are not. They answer three different questions, and collapsing them
loses information that a reader of a validation report needs:

* `ARCH-TOOL-CORE-001` §6 names nine **categories** — who emitted this.
* `projections.md` PROJ-07 names six **validation dimensions** — what correctness is being
  claimed.
* `core.md` line 91 names four **bands** — how to treat it.

A single four-value enum, as the wave plan first proposed, contradicts core.md's own nine and
cannot say that a cross-record rule and a renderer produced findings about the same claim.

`ValidationClaim` is defined at PROJ-07's six rather than DATA-31's four. The four map onto the
six — `DATA31_MEANINGS` below makes that mapping executable rather than asserted in prose — and
defining the wider set now means W7 adds generators without migrating every stored diagnostic.
Two of the six are unreachable until then, which is the same reservation W4 makes for the
projection fields in its manifest.
"""

from collections.abc import Mapping
from enum import StrEnum

__all__ = [
    "DATA31_MEANINGS",
    "DiagnosticCategory",
    "Disposition",
    "Severity",
    "ValidationClaim",
]


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DiagnosticCategory(StrEnum):
    """Who emitted it. `ARCH-TOOL-CORE-001` §6, all nine."""

    AUTHORING_PARSE = "authoring_parse"
    RECORD_VALIDATION = "record_validation"
    CROSS_RECORD_VALIDATION = "cross_record_validation"
    GRAPH_ANALYSIS = "graph_analysis"
    RELEASE_COHERENCE = "release_coherence"
    NOTATION_MAPPING = "notation_mapping"
    SCHEMA_INTEROPERABILITY = "schema_interoperability"
    RENDERING = "rendering"
    # Reserved for W9. `domain/engineering.py` is explicit that `Diagnostic` must never carry
    # source-code quality signals, so a test forbids any W1 rule from using this value and the
    # boundary is checked in both directions.
    ENGINEERING_QUALIFICATION = "engineering_qualification"


class ValidationClaim(StrEnum):
    """What correctness is being claimed. PROJ-07, all six.

    Passing an XML schema check does not establish that a workflow is operationally correct.
    Keeping these apart is the whole point: a report that says "valid" without saying *which*
    claim it validated is the failure mode DATA-31 exists to prevent.
    """

    CANONICAL_STRUCTURE = "canonical_structure"
    CROSS_MODEL_SEMANTICS = "cross_model_semantics"
    NOTATION_SEMANTICS = "notation_semantics"
    SCHEMA_SYNTAX = "schema_syntax"
    RENDERER = "renderer"
    REAL_WORLD_CORRECTNESS = "real_world_correctness"


class Disposition(StrEnum):
    """How to treat it. core.md line 91, all four.

    Separate from `Severity` because an evidence gap and a profile expectation are both warnings
    and are not the same thing. DATA-41 needs that difference: a gap is information to preserve,
    while a profile expectation is a local policy a different profile might not hold.
    """

    HARD_STRUCTURAL_ERROR = "hard_structural_error"
    EVIDENCE_GAP = "evidence_gap"
    PROFILE_EXPECTATION = "profile_expectation"
    HUMAN_REVIEW = "human_review"


DATA31_MEANINGS: Mapping[str, frozenset[ValidationClaim]] = {
    "schema_validity": frozenset({ValidationClaim.SCHEMA_SYNTAX}),
    "notation_validity": frozenset({ValidationClaim.NOTATION_SEMANTICS, ValidationClaim.RENDERER}),
    "architectural_consistency": frozenset(
        {ValidationClaim.CANONICAL_STRUCTURE, ValidationClaim.CROSS_MODEL_SEMANTICS}
    ),
    "real_world_correctness": frozenset({ValidationClaim.REAL_WORLD_CORRECTNESS}),
}
"""DATA-31's four meanings of validation success, as a partition of PROJ-07's six claims.

Written down so the relationship is checkable. `tests/unit/test_taxonomy.py` asserts it is a true
partition — every claim covered exactly once — which is what makes "we defined six instead of
four" a refinement rather than a contradiction.
"""
