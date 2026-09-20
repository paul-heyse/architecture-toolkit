"""Shared fixtures and qualification profiles.

Fixture scope defaults to function (CORE-51); widen only where resource cost or genuine
immutability justifies it, and say why at the fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, settings

ROOT = Path(__file__).resolve().parents[1]

# CORE-47: explicit, version-controlled profiles. `dev` is the fast developer loop, `ci` the
# default gate, `deep` a deliberate longer exploration run for W9's state machines. No profile
# performs network access.
settings.register_profile("dev", max_examples=25, deadline=None)
settings.register_profile(
    "ci",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile("deep", max_examples=1000, stateful_step_count=50, deadline=None)
settings.load_profile("ci")


@pytest.fixture
def minimal_model_source() -> dict[str, Any]:
    """The synthetic authoring fixture, parsed.

    Function-scoped on purpose: tests mutate the mapping to build invalid variants, and a shared
    instance would leak those mutations between tests.
    """
    from architecture_toolkit.domain.authoring import parse_source

    source = ROOT / "examples/minimal/model.yaml"
    loaded = parse_source(source.read_text(), source_id=str(source))
    return json.loads(loaded.json_text())
