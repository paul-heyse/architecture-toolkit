"""The materialized snapshot provider and its version discipline (DATA-34, DATA-51)."""

from pathlib import Path

import pytest

from architecture_toolkit.domain.protocols import SnapshotProvider
from architecture_toolkit.domain.providers import Materialization
from architecture_toolkit.storage.errors import UnknownTableError
from architecture_toolkit.storage.snapshot import (
    LIBRARIES,
    MaterializedPyArrowSnapshotProvider,
    require_version,
)


@pytest.mark.unit
@pytest.mark.requirement("DATA-51")
@pytest.mark.parametrize("version", [0, 1, 7, 10_000])
def test_an_explicit_nonnegative_version_is_accepted(version: int) -> None:
    assert require_version(version) == version


@pytest.mark.unit
@pytest.mark.requirement("DATA-51")
@pytest.mark.parametrize(
    ("version", "why"),
    [
        (-1, "negative"),
        (True, "bool is an int subclass and would read version 1"),
        (1.0, "a float is not a version"),
        ("0", "a string is not a version"),
        (None, "absent is not explicit"),
    ],
)
def test_anything_that_is_not_an_explicit_version_is_refused(version: object, why: str) -> None:
    """`True` is the one that matters: `isinstance(True, int)` is `True` in Python."""
    with pytest.raises(ValueError, match="explicit nonnegative table version"):
        # Deliberately ill-typed: the parameter is `int` so callers are checked statically,
        # and this test is the runtime half that catches what a caller smuggles past that.
        require_version(version)  # type: ignore[arg-type]
    assert why


@pytest.mark.unit
@pytest.mark.requirement("DATA-34")
def test_the_description_is_deterministic_and_names_the_locked_libraries() -> None:
    """§11B: a provider reports its identity and the libraries its correctness rests on.

    Deterministic so W9 can embed it in evidence and compare across runs — no paths, no times.
    """
    provider = MaterializedPyArrowSnapshotProvider({})
    description = provider.describe()
    assert description.provider_type == "MaterializedPyArrowSnapshotProvider"
    assert description.materialization is Materialization.MATERIALIZED
    assert description.preserves_typed_empties is True
    assert description.native_ffi_enabled is False
    assert [name for name, _ in description.library_versions] == sorted(LIBRARIES)
    assert all(bool(value) for _, value in description.library_versions)
    # Determinism: a second provider over a different location set describes identically.
    assert MaterializedPyArrowSnapshotProvider({"elements": Path("/x")}).describe() == description


@pytest.mark.unit
@pytest.mark.requirement("DATA-34")
def test_a_table_the_provider_was_not_given_is_an_unknown_table() -> None:
    """Nothing is resolved by convention: a provider that can guess a path can guess a wrong one."""
    provider = MaterializedPyArrowSnapshotProvider({"elements": Path("/nowhere")})
    with pytest.raises(UnknownTableError):
        provider.read("relationships", version=0)
    with pytest.raises(UnknownTableError):
        provider.schema_for("relationships", version=0)
    with pytest.raises(UnknownTableError):
        provider.open("relationships", version=0)


@pytest.mark.unit
@pytest.mark.requirement("CORE-58", "DATA-34")
def test_the_shipped_provider_satisfies_the_protocol_at_run_time() -> None:
    """Signature conformance is static — `tests/static/protocol_conformance.py` — and this is the
    runtime half, which only compares method names."""
    assert isinstance(MaterializedPyArrowSnapshotProvider({}), SnapshotProvider)


@pytest.mark.unit
@pytest.mark.requirement("DATA-51")
def test_the_version_is_checked_before_the_location_is_touched() -> None:
    """A bad version fails the same way whether or not the table exists."""
    provider = MaterializedPyArrowSnapshotProvider({"elements": Path("/nowhere")})
    with pytest.raises(ValueError, match="explicit nonnegative table version"):
        provider.read("elements", version=-1)
