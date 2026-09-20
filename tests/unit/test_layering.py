"""Package layering, checked at the import level (CORE-01, CORE-66, DATA-01)."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "architecture_toolkit"


def runtime_imports(path: Path) -> set[str]:
    """Every module imported at runtime, excluding anything under `if TYPE_CHECKING:`."""
    tree = ast.parse(path.read_text())
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            named = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
                isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
            )
            if named:
                guarded |= {id(child) for child in ast.walk(node)}
    found: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.unit
@pytest.mark.requirement("CORE-01", "CORE-07")
def test_the_domain_never_imports_validation_at_runtime() -> None:
    """The layering that keeps the canonical flow from inverting.

    `validation` imports `domain`; the reverse would make the domain depend on the rules that
    judge it. The one permitted edge is `protocols.py`'s `TYPE_CHECKING` block, which gives
    `ValidatorAdapter` a real signature and imports nothing at runtime — protocols are
    structural, so conformance needs no runtime import.
    """
    offenders = {
        path.relative_to(SRC).as_posix(): sorted(
            module
            for module in runtime_imports(path)
            if "architecture_toolkit.validation" in module
        )
        for path in (SRC / "domain").rglob("*.py")
    }
    leaked = {path: modules for path, modules in offenders.items() if modules}
    assert not leaked, f"domain imports validation at runtime: {leaked}"


@pytest.mark.unit
@pytest.mark.requirement("CORE-58")
def test_protocols_does_take_the_type_only_edge() -> None:
    """The positive half: the exception exists and is where it is claimed to be.

    Without this, the test above would keep passing if someone removed the typing and left
    `ValidatorAdapter.validate` taking `object`.
    """
    source = (SRC / "domain" / "protocols.py").read_text()
    assert "if TYPE_CHECKING:" in source
    assert "from architecture_toolkit.validation.diagnostics import Diagnostic" in source
    assert "architecture_toolkit.validation" not in "\n".join(
        sorted(runtime_imports(SRC / "domain" / "protocols.py"))
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-66")
def test_validation_and_engineering_evidence_stay_apart() -> None:
    """`domain/engineering.py` is explicit that Diagnostic must not carry code-quality signals.

    The forward direction was guarded when `engineering.py` landed; this is the reverse, which
    that test deferred until `validation/` existed.
    """
    leaked = {
        path.relative_to(SRC).as_posix(): sorted(
            module for module in runtime_imports(path) if "engineering" in module
        )
        for path in (SRC / "validation").rglob("*.py")
    }
    assert not {path: modules for path, modules in leaked.items() if modules}


@pytest.mark.unit
@pytest.mark.requirement("CORE-66")
def test_a_check_result_can_never_be_read_as_a_diagnostic_severity() -> None:
    """Two vocabularies about two different things, kept unambiguous by value."""
    from architecture_toolkit.domain.engineering import CheckResult
    from architecture_toolkit.validation.taxonomy import Disposition, Severity

    results = {member.value for member in CheckResult}
    assert not results & {member.value for member in Severity}
    assert not results & {member.value for member in Disposition}


@pytest.mark.unit
@pytest.mark.requirement("DATA-01")
def test_validation_does_no_graph_or_storage_work() -> None:
    """DATA-01 gives NetworkX a bounded role behind W5's facade.

    Containment cycles use `graphlib` from the standard library instead, so this wave does not
    open a second graph entry point before the first one exists.
    """
    banned = {"networkx", "pyarrow", "deltalake", "datafusion"}
    for path in (SRC / "validation").rglob("*.py"):
        imported = {module.split(".")[0] for module in runtime_imports(path)}
        assert not imported & banned, path
