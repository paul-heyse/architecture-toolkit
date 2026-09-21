"""The suite's own conventions, where a convention has a cost somebody pays (CORE-48).

One convention lives here so far: **a Hypothesis property that draws a whole model is marked
`slow`**. Those 25 tests are 106 of the suite's 167 seconds, so `-m "not slow"` is the difference
between a one-minute inner loop and a three-minute one. A convention nothing checks is a sentence
in a document, and the next whole-model property would be written without the marker within a wave.

The rule is structural rather than a stopwatch reading, because a threshold measured on one machine
is not a property of the test. A model draw builds eleven collections and digests them; that is why
these are the expensive ones, and it is visible in the `@given` line.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"

MODEL_DRAWS = frozenset({"full_models", "coherent_models", "data"})
"""The three spellings of "this property draws a whole model".

`full_models()` and `coherent_models()` say so outright. `st.data()` is the composing form — every
use of it in this suite draws a model and then edits it, which is strictly more work than drawing
one. A future `st.data()` property that draws something small would be marked `slow` for no reason;
that is the cheap direction to be wrong in, and the guard says so when it fires.
"""


def _drawn_names(decorator: ast.expr) -> set[str]:
    """Every callable named inside one `@given(...)`, positional or keyword."""
    if not isinstance(decorator, ast.Call):
        return set()
    names: set[str] = set()
    for node in ast.walk(decorator):
        if isinstance(node, ast.Call):
            called = node.func
            if isinstance(called, ast.Name):
                names.add(called.id)
            elif isinstance(called, ast.Attribute):
                names.add(called.attr)
    return names


def _is_given(decorator: ast.expr) -> bool:
    call = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(call, ast.Name) and call.id == "given"


def _marks(function: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for decorator in function.decorator_list:
        node = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            if node.value.attr == "mark":
                names.add(node.attr)
    return names


def _module_level_tests() -> list[tuple[str, ast.FunctionDef]]:
    """Top-level `test_*` functions only.

    A `@given` on a function nested inside a test — `test_strategies.py` has two — is a
    demonstration of the strategy machinery rather than a property over the model, and neither
    costs a measurable second.
    """
    found: list[tuple[str, ast.FunctionDef]] = []
    for path in sorted(TESTS.rglob("test_*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                found.append((f"{path.relative_to(ROOT)}::{node.name}", node))
    return found


@pytest.mark.unit
@pytest.mark.requirement("CORE-48")
def test_every_property_that_draws_a_whole_model_is_marked_slow() -> None:
    """The marker is what makes `-m "not slow"` mean something, so it cannot be optional."""
    unmarked = [
        node_id
        for node_id, function in _module_level_tests()
        if any(
            _is_given(decorator) and _drawn_names(decorator) & MODEL_DRAWS
            for decorator in function.decorator_list
        )
        and "slow" not in _marks(function)
    ]
    assert not unmarked, (
        f"these properties draw a whole model and are not marked slow: {unmarked}. "
        f"Add `@pytest.mark.slow` under `@pytest.mark.property`, or draw something smaller."
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-48")
def test_slow_means_exactly_that_and_nothing_else() -> None:
    """The converse, so `slow` does not become the marker for "this one annoyed me once".

    A second reason to mark a test slow is a reason to give it a second marker, not to widen this
    one until skipping it stops being safe.
    """
    miscategorized = [
        node_id
        for node_id, function in _module_level_tests()
        if "slow" in _marks(function)
        and not any(
            _is_given(decorator) and _drawn_names(decorator) & MODEL_DRAWS
            for decorator in function.decorator_list
        )
    ]
    assert not miscategorized, (
        f"these are marked slow without drawing a whole model: {miscategorized}. "
        f"`slow` is the whole-model property marker; give another cost its own marker."
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-48")
def test_the_inner_loop_is_not_empty_and_is_not_the_whole_suite() -> None:
    """Both guards above pass vacuously over a suite with no properties in it at all."""
    marked = [node_id for node_id, node in _module_level_tests() if "slow" in _marks(node)]
    assert len(marked) >= 20, f"the whole-model properties stopped being found: {marked}"
    assert len(marked) < len(_module_level_tests()) // 2, "slow has grown into the whole suite"
