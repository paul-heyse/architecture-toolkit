"""The validate command's exit codes and rendering (CORE-19)."""

import json
import sys
from pathlib import Path

import pytest

from architecture_toolkit import cli

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
FORBIDDEN = ROOT / "tests" / "fixtures" / "authoring" / "forbidden"
NESTED = ROOT / "tests" / "fixtures" / "authoring" / "nested_foreign_key.yaml"


def _run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["architecture", *argv])
    return cli.main()


@pytest.mark.unit
@pytest.mark.requirement("CORE-16", "CORE-19")
def test_a_forbidden_construct_exits_three_with_a_located_block(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = FORBIDDEN / "alias.yaml"
    assert _run(monkeypatch, "validate", str(fixture)) == cli.EXIT_UNREADABLE
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"{fixture}:3:8"
    assert lines[1] == "ERROR CORE.YAML.ALIAS"


@pytest.mark.unit
@pytest.mark.requirement("CORE-19")
def test_a_record_failure_exits_one_with_its_position(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text(EXAMPLE.read_text().replace("timeout_ms: 30000", "timeout_ms: soon"))
    assert _run(monkeypatch, "validate", str(broken)) == cli.EXIT_DIAGNOSTICS
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith(f"{broken}:87:")
    assert lines[1] == "ERROR CORE.DOMAIN.INVALID_TYPE"
    assert lines[2] == "elements[5].detail.timeout_ms"


@pytest.mark.unit
@pytest.mark.requirement("CORE-19")
def test_the_example_validates_and_its_gaps_are_located(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, "validate", str(EXAMPLE), "--format", "json") == cli.EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["diagnostics"], "the example carries deliberate gaps"
    for diagnostic in report["diagnostics"]:
        assert diagnostic["source_location"]["line"] is not None
        assert diagnostic["source_location"]["source_id"] == str(EXAMPLE)


@pytest.mark.unit
@pytest.mark.requirement("CORE-19")
def test_a_hard_cross_record_error_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(monkeypatch, "validate", str(NESTED)) == cli.EXIT_DIAGNOSTICS
    out = capsys.readouterr().out
    assert f"{NESTED}:112:35\nERROR CORE.INTERFACE.UNRESOLVED_FOREIGN_KEY" in out


@pytest.mark.unit
def test_a_missing_file_exits_three(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert _run(monkeypatch, "validate", str(tmp_path / "absent.yaml")) == cli.EXIT_UNREADABLE
    assert "CORE.YAML.SYNTAX" in capsys.readouterr().out
