"""The operator surface for queries and traversals (DATA-48, DATA-49, CORE-28).

Every command is exercised through `main` with a real store, because the interesting failures are
the argument-handling ones and those do not exist at the library level: a command line has only
strings, and something has to decide that `--param max_depth=5` is an integer.
"""

import json
import sys
from pathlib import Path

import pytest

from architecture_toolkit.cli import EXIT_OK, EXIT_USAGE, main
from architecture_toolkit.domain.model import Model
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import Publisher


def run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["architecture", *argv])
    return main()


@pytest.fixture
def published(store: ReleaseStore, example_model: Model, publish_release: Publisher) -> Path:
    publish_release("rel-0001", example_model, expected_parent=None)
    return store.root


@pytest.mark.integration
@pytest.mark.requirement("DATA-48")
def test_recipes_lists_every_recipe_and_describes_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(monkeypatch, "recipes") == EXIT_OK
    listing = capsys.readouterr().out
    assert "capability_coverage_matrix" in listing
    assert "containment_hierarchy" in listing

    assert run(monkeypatch, "recipes", "containment_hierarchy") == EXIT_OK
    described = capsys.readouterr().out
    assert "$root_element_id : string (required)" in described
    assert "$max_depth : integer (required)" in described
    assert "WITH RECURSIVE" in described


@pytest.mark.integration
@pytest.mark.requirement("DATA-48")
def test_an_unknown_recipe_is_a_usage_error_that_lists_the_real_ones(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_code:
        run(monkeypatch, "recipes", "no_such_recipe")

    assert exit_code.value.code == EXIT_USAGE
    assert "unknown query recipe" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.requirement("DATA-48", "DATA-46")
def test_query_runs_a_recipe_against_the_current_release(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    assert run(monkeypatch, "query", "capability_coverage_matrix", "--store", str(published)) == (
        EXIT_OK
    )

    printed = capsys.readouterr().out
    assert "capability_coverage_matrix v1.0.0 on rel-0001" in printed
    assert "capability-1" in printed


@pytest.mark.integration
@pytest.mark.requirement("DATA-48", "DATA-18")
def test_query_types_each_parameter_by_the_recipes_own_declaration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    """`--param max_depth=5` is an integer because the recipe says so, not because it looks it."""
    code = run(
        monkeypatch,
        "query",
        "containment_hierarchy",
        "--store",
        str(published),
        "--param",
        "root_element_id=system-1",
        "--param",
        "max_depth=5",
        "--format",
        "json",
    )

    assert code == EXIT_OK
    rows = json.loads(capsys.readouterr().out)
    assert rows == [
        {
            "element_id": "component-1",
            "name": "Request handler",
            "relationship_id": "rel-1",
            "depth": 1,
        }
    ]


@pytest.mark.integration
@pytest.mark.requirement("DATA-18")
def test_a_parameter_of_the_wrong_type_is_refused_before_the_engine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    with pytest.raises(SystemExit) as exit_code:
        run(
            monkeypatch,
            "query",
            "containment_hierarchy",
            "--store",
            str(published),
            "--param",
            "root_element_id=system-1",
            "--param",
            "max_depth=deep",
        )

    assert exit_code.value.code == EXIT_USAGE
    assert "$max_depth is an integer" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.requirement("DATA-18")
def test_an_undeclared_parameter_is_refused_and_says_what_the_recipe_takes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    with pytest.raises(SystemExit) as exit_code:
        run(
            monkeypatch,
            "query",
            "capability_coverage_matrix",
            "--store",
            str(published),
            "--param",
            "sneaky=1",
        )

    assert exit_code.value.code == EXIT_USAGE
    assert "declares no parameter 'sneaky'" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.requirement("DATA-47")
def test_a_comparison_recipe_is_refused_on_the_single_release_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    """Better than letting it fail in the planner with `failed to resolve schema: base`."""
    with pytest.raises(SystemExit) as exit_code:
        run(
            monkeypatch,
            "query",
            "application_ownership_across_releases",
            "--store",
            str(published),
        )

    assert exit_code.value.code == EXIT_USAGE
    assert "compares two releases" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.requirement("DATA-49")
def test_plan_prints_all_three_plans_and_says_they_are_diagnostics(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    assert run(monkeypatch, "plan", "capability_coverage_matrix", "--store", str(published)) == (
        EXIT_OK
    )

    printed = capsys.readouterr().out
    assert "--- logical ---" in printed
    assert "--- optimized ---" in printed
    assert "--- physical ---" in printed
    assert "datafusion" in printed
    assert "never part of semantic identity" in printed


@pytest.mark.integration
@pytest.mark.requirement("CORE-28", "DATA-17")
def test_impact_prints_the_path_that_justifies_every_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    """CORE-28 at the operator surface: no result appears without its relationships."""
    assert run(monkeypatch, "impact", "system-1", "--store", str(published)) == EXIT_OK

    printed = capsys.readouterr().out
    assert "potentially_affected" in printed
    assert "rel-1 (contains)" in printed
    assert "rel-1 (contains) -> rel-2 (exposes)" in printed
    assert "rel-7" not in printed, "the documentation edge must not appear in an impact report"


@pytest.mark.integration
@pytest.mark.requirement("CORE-26")
def test_impact_can_list_the_policies_it_will_accept(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(monkeypatch, "impact", "unused", "--policy", "list") == EXIT_OK

    listing = capsys.readouterr().out
    assert "impact.structural" in listing
    assert "trace.requirement_implementation" in listing


@pytest.mark.integration
@pytest.mark.requirement("CORE-26")
def test_an_unknown_policy_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    with pytest.raises(SystemExit) as exit_code:
        run(monkeypatch, "impact", "system-1", "--store", str(published), "--policy", "no.such")

    assert exit_code.value.code == EXIT_USAGE
    assert "unknown graph policy" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.requirement("DATA-46")
def test_a_store_with_no_current_release_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    ReleaseStore.at(tmp_path).initialize()

    with pytest.raises(SystemExit) as exit_code:
        run(monkeypatch, "query", "capability_coverage_matrix", "--store", str(tmp_path))

    assert exit_code.value.code == EXIT_USAGE
    assert "No current release" in capsys.readouterr().err
