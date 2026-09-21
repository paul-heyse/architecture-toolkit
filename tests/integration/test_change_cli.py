"""The six lifecycle verbs W6 adds to the CLI (DATA-38).

`validate` and `publish` already shipped at W1 and W4, so these complete DATA-38's eight. Each test
asserts what the command *says*, not merely that it exited zero: a verb that printed nothing and
returned `EXIT_OK` would pass every exit-code assertion in this file and none of the others.
"""

import json
import sys
from pathlib import Path

import jsonschema
import pytest

from architecture_toolkit.cli import EXIT_DIAGNOSTICS, EXIT_OK, EXIT_USAGE, main
from architecture_toolkit.domain.model import Model
from architecture_toolkit.releases.recovery import is_orphan
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import Publisher, rename_first_element

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "schemas" / "change-record.schema.json"

RENAME = {
    "change_set_id": "cs-0001",
    "model_id": "sample-service",
    "commands": [
        {
            "command": "rename_element",
            "element_id": "capability-1",
            "new_name": "Portfolio Technology Evaluation",
        }
    ],
}


def run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["architecture", *argv])
    return main()


@pytest.fixture
def published(store: ReleaseStore, example_model: Model, publish_release: Publisher) -> Path:
    publish_release("rel-0001", example_model, expected_parent=None)
    return store.root


@pytest.fixture
def two_releases(store: ReleaseStore, example_model: Model, publish_release: Publisher) -> Path:
    publish_release("rel-0001", example_model, expected_parent=None)
    publish_release(
        "rel-0002",
        rename_first_element(example_model, "Portfolio Technology Evaluation"),
        expected_parent="rel-0001",
    )
    return store.root


def change_set_file(tmp_path: Path) -> Path:
    path = tmp_path / "change-set.json"
    path.write_text(json.dumps(RENAME))
    return path


# -- baseline ----------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-38")
def test_baseline_summarises_the_current_release(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    assert run(monkeypatch, "baseline", "--store", str(published)) == EXIT_OK

    printed = capsys.readouterr().out
    assert "sample-service" in printed
    assert "10  elements" in printed
    assert "notation_bindings" in printed


@pytest.mark.integration
@pytest.mark.requirement("DATA-38")
def test_baseline_refuses_a_store_with_nothing_published(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with pytest.raises(SystemExit):
        run(monkeypatch, "baseline", "--store", str(tmp_path / "empty"))

    assert "no current release" in capsys.readouterr().err


# -- change ------------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-38", "CORE-10")
def test_change_previews_without_writing_anything(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    store: ReleaseStore,
    published: Path,
    tmp_path: Path,
) -> None:
    """The first four steps are a dry run, so the command has no way to keep the result."""
    before = store.release_ids()

    assert run(
        monkeypatch, "change", str(change_set_file(tmp_path)), "--store", str(published)
    ) == (EXIT_OK)

    printed = capsys.readouterr().out
    assert "elements.capability-1  element_renamed" in printed
    assert "Portfolio Technology Evaluation" in printed
    assert store.release_ids() == before
    assert store.current_id() == "rel-0001"

    # DATA-26's other half: who, why and against what. A field an operator never sees is a field
    # nobody can act on, so the provenance is printed and asserted rather than only serialized.
    assert "by architecture-cli (agent via architecture-toolkit)" in printed
    assert "applying change set cs-0001" in printed
    assert "against rel-0001 -> not yet published" in printed
    assert "impact, under impact.structural" in printed


@pytest.mark.integration
@pytest.mark.requirement("DATA-38", "DATA-26", "CORE-12")
def test_change_json_validates_against_the_generated_change_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    published: Path,
    tmp_path: Path,
) -> None:
    """A published contract nothing is checked against is the same claim as an empty test."""
    assert (
        run(
            monkeypatch,
            "change",
            str(change_set_file(tmp_path)),
            "--store",
            str(published),
            "--format",
            "json",
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    jsonschema.validate(
        payload,
        {
            "$schema": contract["$schema"],
            "$defs": contract["$defs"],
            "$ref": "#/$defs/ArchitectureChangeSet",
        },
    )
    assert payload["authored_by"]["author_kind"] == "agent"
    assert payload["new_release_id"] is None, "a preview describes no published release"
    assert payload["changes"]["records"][0]["kinds"] == ["element_renamed"]


@pytest.mark.integration
@pytest.mark.requirement("DATA-38")
def test_change_refuses_a_change_set_that_will_not_parse(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    published: Path,
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"change_set_id": "cs-0001"}')

    with pytest.raises(SystemExit):
        run(monkeypatch, "change", str(broken), "--store", str(published))

    assert "broken.json" in capsys.readouterr().err


# -- diff --------------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-38", "DATA-26")
def test_diff_explains_what_changed_between_two_releases(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], two_releases: Path
) -> None:
    assert (
        run(
            monkeypatch,
            "diff",
            "--base",
            "rel-0001",
            "--candidate",
            "rel-0002",
            "--store",
            str(two_releases),
        )
        == EXIT_OK
    )

    printed = capsys.readouterr().out
    assert "rel-0001 -> rel-0002" in printed
    assert "elements.capability-1  element_renamed" in printed
    assert "name:" in printed


@pytest.mark.integration
@pytest.mark.requirement("DATA-26", "DATA-31")
def test_diff_keeps_presentation_changes_out_of_the_narrative(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """The hard gate at the operator's surface, where it is what somebody actually reads.

    Both assertions matter: the change is reported (so the command is not simply silent) and it is
    reported below a line that says it is not architectural change.
    """
    binding = example_model.notation_bindings[0]
    relaid = example_model.model_validate(
        dict(example_model)
        | {
            "notation_bindings": (
                binding.model_validate(dict(binding) | {"link_target": "diagrams/review.svg#x"}),
            )
        }
    )
    publish_release("rel-0001", example_model, expected_parent=None)
    publish_release("rel-0002", relaid, expected_parent="rel-0001")

    assert (
        run(
            monkeypatch,
            "diff",
            "--base",
            "rel-0001",
            "--candidate",
            "rel-0002",
            "--store",
            str(store.root),
        )
        == EXIT_OK
    )
    narrative_only = capsys.readouterr().out
    assert "no semantic change" in narrative_only
    assert "link_target" not in narrative_only

    assert (
        run(
            monkeypatch,
            "diff",
            "--base",
            "rel-0001",
            "--candidate",
            "rel-0002",
            "--store",
            str(store.root),
            "--include-presentation",
        )
        == EXIT_OK
    )
    with_layout = capsys.readouterr().out
    assert "presentation only (1), not architectural change" in with_layout
    assert "link_target: layout_only" in with_layout


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_diff_refuses_a_baseline_against_an_alternative(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    publish_release("rel-0001", example_model, expected_parent=None)
    alternative = publish_release(
        "rel-0002", rename_first_element(example_model, "Thinner"), expected_parent="rel-0001"
    )
    store.manifest_path(alternative.release_id).write_text(
        alternative.model_validate(
            dict(alternative)
            | {
                "parent_release_id": None,
                "scenario_id": "alt-thinner",
                "baseline_release_id": "rel-0001",
            }
        ).model_dump_json(indent=2)
    )

    with pytest.raises(SystemExit):
        run(
            monkeypatch,
            "diff",
            "--base",
            "rel-0001",
            "--candidate",
            "rel-0002",
            "--store",
            str(store.root),
        )

    assert "not a later revision of its baseline" in capsys.readouterr().err


# -- review ------------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-38")
def test_review_records_a_decision_on_a_change_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    published: Path,
    tmp_path: Path,
) -> None:
    assert (
        run(
            monkeypatch,
            "change",
            str(change_set_file(tmp_path)),
            "--store",
            str(published),
            "--format",
            "json",
        )
        == EXIT_OK
    )
    report = tmp_path / "report.json"
    report.write_text(capsys.readouterr().out)

    assert (
        run(
            monkeypatch,
            "review",
            str(report),
            "--decision",
            "approved",
            "--reviewer",
            "paul",
            "--note",
            "Matches the accepted decision.",
        )
        == EXIT_OK
    )

    printed = capsys.readouterr().out
    assert "review: approved by paul at " in printed
    assert "rationale" not in printed, "this change set carries none, so none is claimed"
    reviewed = json.loads(report.read_text())
    assert reviewed["review"]["decision"] == "approved"
    assert reviewed["review"]["reviewer"]["author_id"] == "paul"
    assert reviewed["review"]["note"] == "Matches the accepted decision."


# -- persist -----------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-38")
def test_persist_writes_a_manifest_and_leaves_the_pointer_alone(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
    tmp_path: Path,
) -> None:
    publish_release("rel-0001", example_model, expected_parent=None)
    source = tmp_path / "model.yaml"
    source.write_text(
        (ROOT / "examples" / "minimal" / "model.yaml")
        .read_text()
        .replace("name: Handle customer requests", "name: Portfolio Technology Evaluation")
    )

    assert (
        run(
            monkeypatch,
            "persist",
            str(source),
            "--store",
            str(store.root),
            "--expect-parent",
            "rel-0001",
        )
        == EXIT_OK
    )

    printed = capsys.readouterr().out
    assert "persisted rel-0002" in printed
    assert "not current: rel-0001 still is" in printed
    assert store.has_manifest("rel-0002")
    assert store.current_id() == "rel-0001"
    assert is_orphan(store, "rel-0002")

    # And `resume` finishes it, so persist is a step rather than a dead end.
    assert run(monkeypatch, "resume", "rel-0002", "--store", str(store.root)) == EXIT_OK
    assert store.current_id() == "rel-0002"


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_persist_refuses_half_an_alternative(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = ROOT / "examples" / "minimal" / "model.yaml"

    with pytest.raises(SystemExit):
        run(
            monkeypatch,
            "persist",
            str(source),
            "--store",
            str(tmp_path / "s"),
            "--expect-parent",
            "",
            "--scenario",
            "alt-a",
        )

    assert "--scenario and --baseline are set together" in capsys.readouterr().err


# -- output ------------------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-38")
def test_output_is_typed_and_truthful_about_not_being_implemented(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], published: Path
) -> None:
    """W8 replaces this. Until then it names the wave rather than failing vaguely."""
    assert run(monkeypatch, "output", "--store", str(published)) == EXIT_USAGE

    printed = capsys.readouterr().out
    assert "not implemented" in printed
    assert "W8" in printed

    assert run(monkeypatch, "output", "--store", str(published), "--format", "json") == EXIT_USAGE
    payload = json.loads(capsys.readouterr().out)
    assert payload["release_id"] == "rel-0001"
    assert "PROJ-35" in payload["reason"]


# -- releases --verify now asks three questions --------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-21", "DATA-28")
def test_verify_checks_the_chain_as_well_as_the_bytes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], two_releases: Path
) -> None:
    """`chain_breaks` was written at W4 and reachable only from its own test until now."""
    assert run(monkeypatch, "releases", "--store", str(two_releases), "--verify") == EXIT_OK

    assert "the chain is navigable" in capsys.readouterr().out


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_verify_reports_an_alternative_positioned_as_a_revision(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
) -> None:
    """The negative control for the test above, written into the store the way a bad tool would."""
    publish_release("rel-0001", example_model, expected_parent=None)
    second = publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )
    store.manifest_path("rel-0002").write_text(
        second.model_validate(
            dict(second) | {"scenario_id": "alt-a", "baseline_release_id": "rel-0000"}
        ).model_dump_json(indent=2)
    )

    assert run(monkeypatch, "releases", "--store", str(store.root), "--verify") == (
        EXIT_DIAGNOSTICS
    )

    printed = capsys.readouterr().out
    assert "CORE.RELEASE.ALTERNATIVE_LINE_BROKEN" in printed


# -- compare (DATA-28) --------------------------------------------------------------------------


def publish_alternative(root: Path, scenario: str = "alt-thinner-api") -> ReleaseStore:
    """An alternative in its own store root, which is the separation `--store` already provides."""
    from architecture_toolkit.domain.authoring import parse_model, parse_source
    from architecture_toolkit.releases.candidate import ReleaseCandidate
    from architecture_toolkit.releases.provenance import source_bundle
    from architecture_toolkit.releases.publication import PublicationRequest, publish
    from tests.integration.conftest import MOMENT

    store = ReleaseStore.at(root).initialize()
    text = (ROOT / "examples" / "minimal" / "model.yaml").read_text()
    thinner = text.replace("timeout_ms: 30000", "timeout_ms: 5000")
    publish(
        PublicationRequest(
            store=store,
            candidate=ReleaseCandidate(
                release_id="rel-0001",
                model=parse_model(parse_source(thinner, source_id="alt")),
                source_bundle=source_bundle(source_id="alt", text=thinner),
                scenario_id=scenario,
                baseline_release_id="rel-0001",
            ),
            expected_parent=None,
            now=lambda: MOMENT,
            generator_commit="abc1234",
        )
    )
    return store


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_compare_explains_an_alternative_without_calling_it_a_change(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    published: Path,
    tmp_path: Path,
) -> None:
    """DATA-28's comparison needs an operator path, or it is a library function nobody can reach."""
    alternative = publish_alternative(tmp_path / "alternative")

    assert (
        run(
            monkeypatch,
            "compare",
            "--baseline",
            "rel-0001",
            "--alternative",
            "rel-0001",
            "--store",
            str(alternative.root),
            "--baseline-store",
            str(published),
        )
        == EXIT_OK
    )

    printed = capsys.readouterr().out
    assert "alternative alt-thinner-api" in printed
    assert "not a revision; neither supersedes the other" in printed
    assert "elements.interface-1  interface_contract_changed" in printed
    assert "detail.timeout_ms: 30000 -> 5000" in printed


@pytest.mark.integration
@pytest.mark.requirement("DATA-28", "CORE-12")
def test_compare_json_is_an_alternative_comparison_and_not_a_change_set(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    published: Path,
    tmp_path: Path,
) -> None:
    """The type-level separation, at the surface where somebody might try to publish the output."""
    import jsonschema

    alternative = publish_alternative(tmp_path / "alternative")
    assert (
        run(
            monkeypatch,
            "compare",
            "--baseline",
            "rel-0001",
            "--alternative",
            "rel-0001",
            "--store",
            str(alternative.root),
            "--baseline-store",
            str(published),
            "--format",
            "json",
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    jsonschema.validate(
        payload,
        {
            "$schema": contract["$schema"],
            "$defs": contract["$defs"],
            "$ref": "#/$defs/AlternativeComparison",
        },
    )
    assert payload["scenario_id"] == "alt-thinner-api"
    assert "narrative" not in payload
    assert "change_set_id" not in payload

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            payload,
            {
                "$schema": contract["$schema"],
                "$defs": contract["$defs"],
                "$ref": "#/$defs/ArchitectureChangeSet",
            },
        )


@pytest.mark.integration
@pytest.mark.requirement("DATA-28")
def test_compare_refuses_two_releases_on_the_baseline_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], two_releases: Path
) -> None:
    """The inverse of `diff` refusing a cross-line pair; both directions or neither."""
    with pytest.raises(SystemExit):
        run(
            monkeypatch,
            "compare",
            "--baseline",
            "rel-0001",
            "--alternative",
            "rel-0002",
            "--store",
            str(two_releases),
        )

    assert "is not an alternative" in capsys.readouterr().err
