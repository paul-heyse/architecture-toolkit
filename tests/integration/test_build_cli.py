"""`architecture build`: the projection pipeline end to end (PROJ-01, PROJ-05, CORE-32..36).

The verb had no options, no handler and no test from W0 until now — it raised a usage refusal
pointing at the implementation contract. This is the one projection W7a generates: notation-neutral
Markdown, so CORE-38's "no standards XML from Jinja" is untouched, and real, so the environment,
the contract check and the bundle digest are proven on an artifact rather than a fixture.
"""

import json
import sys
from pathlib import Path

import pytest

from architecture_toolkit.cli import main
from architecture_toolkit.cli_errors import EXIT_OK, EXIT_USAGE
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.projections.generators import GENERATORS, ModelSummaryGenerator
from architecture_toolkit.projections.text import bundle_for, environment
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import Publisher, rename_first_element


def run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["architecture", *argv])
    return main()


@pytest.fixture
def published(store: ReleaseStore, example_model: Model, publish_release: Publisher) -> Path:
    publish_release("rel-0001", example_model, expected_parent=None)
    return store.root


@pytest.mark.integration
@pytest.mark.qualification
@pytest.mark.requirement("PROJ-01", "PROJ-05")
def test_build_writes_the_source_and_reports_where_it_came_from(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    published: Path,
    tmp_path: Path,
    example_model: Model,
) -> None:
    """Four provenance facts, and every one of them is what makes the file explainable."""
    out = tmp_path / "out"
    assert (
        run(
            monkeypatch,
            "build",
            "--store",
            str(published),
            "--into",
            str(out),
            "--format",
            "json",
        )
        == EXIT_OK
    )

    artifact = json.loads(capsys.readouterr().out)
    assert artifact["release_id"] == "rel-0001"
    assert artifact["semantic_input_digest"] == model_digest(example_model)
    assert (
        artifact["template_bundle_digest"]
        == bundle_for(environment(), ModelSummaryGenerator().template).digest
    )
    assert "notation" not in artifact, "Markdown is a format, not a modelling language"

    written = out / artifact["generated_source_locator"]
    assert written.is_file()
    source = written.read_text(encoding="utf-8")
    assert source.startswith("# sample-service\n")
    assert "| view-1 |" in source, "the example's view reaches the generated artifact"


@pytest.mark.integration
@pytest.mark.requirement("CORE-33", "PROJ-05")
def test_the_same_release_builds_the_same_bytes_twice(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    """Determinism through the CLI, not only through the library."""
    digests = []
    for _ in range(2):
        assert run(monkeypatch, "build", "--store", str(published), "--format", "json") == EXIT_OK
        digests.append(json.loads(capsys.readouterr().out)["generated_source_digest"])
    assert digests[0] == digests[1]


@pytest.mark.integration
@pytest.mark.requirement("PROJ-05")
def test_a_changed_model_moves_both_the_input_and_the_output_digest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """The provenance is a claim about a specific model, so it has to move when the model does."""
    publish_release("rel-0001", example_model, expected_parent=None)
    publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )

    built = []
    for release in ("rel-0001", "rel-0002"):
        assert (
            run(
                monkeypatch,
                "build",
                "--store",
                str(store.root),
                "--release",
                release,
                "--format",
                "json",
            )
            == EXIT_OK
        )
        built.append(json.loads(capsys.readouterr().out))

    assert built[0]["semantic_input_digest"] != built[1]["semantic_input_digest"]
    assert built[0]["generated_source_digest"] != built[1]["generated_source_digest"]
    assert built[0]["template_bundle_digest"] == built[1]["template_bundle_digest"], (
        "the templates did not change, so the bundle digest must not"
    )


@pytest.mark.integration
@pytest.mark.requirement("PROJ-05", "CORE-58")
def test_an_unknown_projection_is_refused_and_the_real_ones_are_listed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    """The registry's refusal, the same shape `provider_named` uses.

    A name is how a caller selects a generator, so an unknown one has to say what the choices are
    — otherwise the only way to discover them is to read the source.
    """
    assert run(monkeypatch, "build", "--store", str(published), "--notation", "nope") != EXIT_OK
    printed = capsys.readouterr()
    assert "unknown projection" in printed.out + printed.err
    for name in GENERATORS:
        assert name in printed.out + printed.err


@pytest.mark.integration
@pytest.mark.requirement("PROJ-05")
def test_naming_a_view_is_refused_rather_than_ignored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    """A caller who named a view and got a whole-model artifact would have no way to notice."""
    assert run(monkeypatch, "build", "--store", str(published), "--view", "view-1") != EXIT_OK
    assert "model-level projection" in capsys.readouterr().out


@pytest.mark.integration
@pytest.mark.requirement("PROJ-05")
def test_building_without_a_release_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert run(monkeypatch, "build", "--store", str(tmp_path / "empty")) == EXIT_USAGE
    assert "no current release" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.requirement("PROJ-05")
def test_the_human_form_says_nothing_was_written_when_nothing_was(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    """Without `--into` the artifact is computed and no file exists, which a reader must be told."""
    assert run(monkeypatch, "build", "--store", str(published)) == EXIT_OK
    printed = capsys.readouterr().out
    assert "built proj-rel-0001-model-summary" in printed
    assert "nothing written" in printed
