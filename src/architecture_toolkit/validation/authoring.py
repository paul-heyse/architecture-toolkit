"""Compose the authoring adapter with validation (CORE-19, CORE-20).

`domain/authoring/` reads and edits sources; `validation/` judges models. This module joins them
the way `pipeline.py` joins `build_candidate` with the rules: in `validation/`, so the domain never
imports the layer that judges it. The CLI and the round-trip editor both go through here, which
is what makes a diagnostic caused by an edit point into the new text rather than the old.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from architecture_toolkit.domain.authoring import AuthoringError, parse_model, parse_source
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.registry import BASELINE_PROFILE, Profile
from architecture_toolkit.domain.source import SourceMap
from architecture_toolkit.validation.claims import ValidationClaimReport
from architecture_toolkit.validation.diagnostics import Diagnostic
from architecture_toolkit.validation.locate import locate_report, locate_validation_error
from architecture_toolkit.validation.normalize import normalize_authoring_error
from architecture_toolkit.validation.pipeline import validate_model

__all__ = ["SourceValidation", "validate_source_text"]

type Outcome = Literal["unreadable", "invalid_records", "validated"]


@dataclass(frozen=True, slots=True)
class SourceValidation:
    """What validating one source established, and how far it got.

    `unreadable`: the adapter rejected the text; no model exists. `invalid_records`: Pydantic
    rejected at least one record; no cross-record rule ran. `validated`: every rule ran and
    `report` says what each claim established.
    """

    outcome: Outcome
    diagnostics: tuple[Diagnostic, ...]
    report: ValidationClaimReport | None = None
    model: Model | None = None
    source_map: SourceMap | None = None


def validate_source_text(
    text: str, *, source_id: str, profile: Profile = BASELINE_PROFILE
) -> SourceValidation:
    """Adapter -> JSON -> strict records -> cross-record rules -> located diagnostics."""
    try:
        loaded = parse_source(text, source_id=source_id)
    except AuthoringError as rejected:
        return SourceValidation("unreadable", normalize_authoring_error(rejected))
    try:
        model = parse_model(loaded)
    except ValidationError as invalid:
        located = locate_validation_error(invalid, root=Model, source_map=loaded.source_map)
        return SourceValidation("invalid_records", located, source_map=loaded.source_map)
    report = locate_report(validate_model(model, profile=profile), loaded.source_map)
    return SourceValidation(
        "validated", report.diagnostics, report=report, model=model, source_map=loaded.source_map
    )
