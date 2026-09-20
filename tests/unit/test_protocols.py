"""The Protocol registry stays exhaustive and structurally checkable (CORE-58, CORE-59)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import assert_never

import pytest

from architecture_toolkit.domain import protocols

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "contracts" / "core.md"

# The boundaries docs/contracts/core.md names under "Typed subsystem interfaces".
type Variant = int | str

EXPECTED = frozenset(
    {
        "SourceLoader",
        "SnapshotProvider",
        "ProjectionGenerator",
        "Renderer",
        "ValidatorAdapter",
        "Publisher",
        "QueryExecutor",
        "ArtifactStore",
    }
)


@pytest.mark.unit
@pytest.mark.requirement("CORE-58")
def test_registry_matches_the_contract() -> None:
    """Declared Protocols are exactly the contract's list — no drift in either direction."""
    declared = set(protocols.__all__)
    assert declared == EXPECTED


@pytest.mark.unit
@pytest.mark.requirement("CORE-58")
def test_contract_still_names_these_boundaries() -> None:
    """Guard the other side: if core.md renames a boundary, this test fails, not the registry."""
    text = CONTRACT.read_text()
    missing = [name for name in EXPECTED if not re.search(rf"\b{name}\b", text)]
    assert not missing, f"docs/contracts/core.md no longer names: {missing}"


@pytest.mark.unit
@pytest.mark.requirement("CORE-58")
def test_conformance_is_structural_not_nominal() -> None:
    """A class satisfies a Protocol without inheriting from it."""

    class Conforming:
        def schema_for(self, table: str, *, version: int) -> object:
            return (table, version)

    assert isinstance(Conforming(), protocols.SnapshotProvider)
    assert not isinstance(object(), protocols.SnapshotProvider)


@pytest.mark.unit
@pytest.mark.requirement("CORE-58")
def test_runtime_isinstance_is_only_a_partial_guard() -> None:
    """`runtime_checkable` compares method *names*, never signatures.

    A class with the right method name and the wrong signature passes `isinstance`. Signature
    conformance is a static property, checked by Pyrefly against `tests/static/`; this test pins
    the limitation so nobody mistakes an `isinstance` call for real conformance — the same
    caveat CORE-25 records for `nx.freeze`.
    """

    class WrongSignature:
        def schema_for(self, table: str) -> object:  # no keyword-only version
            return table

    # pyrefly: ignore[unsafe-overlap]
    # The suppression is the point: Pyrefly flags this isinstance call as an unsafe overlap
    # because the signatures diverge. That static error is the real guard; the runtime assertion
    # below only records that isinstance does not provide one.
    assert isinstance(WrongSignature(), protocols.SnapshotProvider)


@pytest.mark.unit
@pytest.mark.requirement("CORE-59")
def test_exhaustive_dispatch_idiom() -> None:
    """match + assert_never is the dispatch idiom.

    The static half of this requirement is the point: adding a variant to a critical union makes
    Pyrefly reject every dispatcher that does not handle it. `tests/static/` holds that fixture.
    This test only pins the runtime behaviour of the same idiom.
    """

    def dispatch(value: Variant) -> str:
        match value:
            case int():
                return "int"
            case str():
                return "str"
            case _:
                assert_never(value)

    assert dispatch(1) == "int"
    assert dispatch("a") == "str"
