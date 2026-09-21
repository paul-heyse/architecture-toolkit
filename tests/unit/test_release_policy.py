"""Release boundaries that are constraints rather than features (DATA-19, DATA-37, DATA-59)."""

import ast
from pathlib import Path

import pytest

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.semantics import semantic_delta, stamp_digests
from architecture_toolkit.releases.audit import CommitAudit
from architecture_toolkit.releases.manifest import SourceBundle
from architecture_toolkit.releases.provenance import digest_bytes, source_bundle

SRC = Path(__file__).resolve().parents[2] / "src" / "architecture_toolkit"
ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"


# -- DATA-19: three histories, kept apart ---------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-19")
def test_the_three_histories_are_carried_by_three_different_types() -> None:
    """Source, storage and architectural history answer three different questions.

    `ARCH-TOOL-DATA-001` §5A: what did the author change, which table files changed, and what
    changed in the design. Conflating any two of them is the mistake the requirement exists to
    prevent, and the defence is that no single type can express more than one of them.
    """
    source_fields = set(SourceBundle.model_fields)
    storage_fields = set(CommitAudit.__slots__)
    from architecture_toolkit.domain.semantics import SemanticDelta

    architectural_fields = set(SemanticDelta.model_fields)

    # Source history: a revision and a digest of what was read.
    assert {"revision", "digest", "snapshot_path"} <= source_fields
    # Storage history: a Delta version and an operation.
    assert {"version", "operation"} <= storage_fields
    # Architectural history: what changed about the model.
    assert {"collections", "base_digest", "candidate_digest"} <= architectural_fields

    # And none of them can stand in for another.
    assert not source_fields & storage_fields
    assert not storage_fields & architectural_fields
    assert not (source_fields & architectural_fields) - {"digest"}


@pytest.mark.unit
@pytest.mark.requirement("DATA-19", "DATA-57")
def test_a_storage_commit_carries_no_architectural_judgement() -> None:
    """Delta says a file was rewritten; it cannot say a capability was retired."""
    audit = CommitAudit(version=3, operation="WRITE", provenance={"table_id": "elements"})
    assert not hasattr(audit, "added")
    assert not hasattr(audit, "removed")
    assert not hasattr(audit, "changed")
    # The architectural answer comes from the domain, over records rather than files.
    model = parse_model(parse_source(EXAMPLE.read_text(), source_id="e"))
    unchanged = semantic_delta(stamp_digests(model), stamp_digests(model))
    assert unchanged.is_empty


# -- DATA-37: source identity -------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-37")
def test_a_source_with_an_immutable_revision_pins_it() -> None:
    bundle = source_bundle(
        source_id="examples/minimal/model.yaml", text="model_id: x\n", revision="a" * 40
    )
    assert bundle.revision == "a" * 40
    assert bundle.digest == digest_bytes(b"model_id: x\n")


@pytest.mark.unit
@pytest.mark.requirement("DATA-37")
def test_a_source_without_a_revision_pins_the_bytes_that_were_read() -> None:
    """DATA-37's point: a mutable URL does not identify a version.

    Where there is no immutable revision, the digest of what was actually read is the claim, and
    `snapshot_path` names the preserved copy. "We read something at this URL once" is not a
    provenance claim anybody can check later.
    """
    text = EXAMPLE.read_text()
    bundle = source_bundle(source_id="https://example.invalid/model.yaml", text=text)
    assert bundle.revision is None
    assert bundle.digest == digest_bytes(text.encode("utf-8"))
    # A different read of a changed source is a different bundle, which is the whole point.
    assert source_bundle(source_id="x", text=text + "\n").digest != bundle.digest


@pytest.mark.unit
@pytest.mark.requirement("DATA-37")
def test_a_source_bundle_is_immutable() -> None:
    bundle = source_bundle(source_id="s", text="x")
    assert isinstance(hash(bundle), int)


# -- DATA-59: proportionate physical design -----------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-59", "DATA-39")
def test_no_partitioning_z_order_or_compaction_tuning_in_the_baseline() -> None:
    """§11H: these stay off the baseline "until measured file-count or scan pressure justifies
    them", and nothing here has measured any.

    A scan rather than a promise, because the tempting moment to add one of these is exactly the
    moment nobody is rereading the contract. `partition_by` is checked as a keyword argument, so
    the word appearing in a docstring explaining why it is absent is not a false positive.
    """
    banned_calls = {"z_order", "compact", "create_checkpoint", "cleanup_metadata", "compact_logs"}
    offenders: dict[str, set[str]] = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in banned_calls:
                found.add(node.attr)
            if isinstance(node, ast.Call):
                found |= {
                    keyword.arg
                    for keyword in node.keywords
                    if keyword.arg in {"partition_by", "partition_filters", "target_file_size"}
                    and not (
                        isinstance(keyword.value, ast.Constant) and keyword.value.value is None
                    )
                }
        if found:
            offenders[path.relative_to(SRC).as_posix()] = found
    assert not offenders, f"physical tuning entered the baseline: {offenders}"


@pytest.mark.unit
@pytest.mark.requirement("DATA-59")
def test_the_scan_catches_a_known_bad_addition() -> None:
    """The guard above is only worth having if it fails on what it claims to catch."""
    source = "dt.optimize.z_order(['element_id'])"
    found = {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr in {"z_order", "compact"}
    }
    assert found == {"z_order"}
