"""Shared publication fixtures for the integration suite (CORE-51).

Function-scoped: every case gets its own `tmp_path` store, because a publication mutates a store
and a shared one would make the fault-injection cases order-dependent — which is the one thing a
deterministic fault-injection suite must not be.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.model import Model
from architecture_toolkit.releases.candidate import ReleaseCandidate
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.provenance import source_bundle
from architecture_toolkit.releases.publication import PublicationRequest, publish
from architecture_toolkit.releases.store import ReleaseStore

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
MOMENT = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)

type Publisher = Callable[..., ArchitectureRelease]


@pytest.fixture
def example_model() -> Model:
    return parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))


@pytest.fixture
def store(tmp_path: Path) -> ReleaseStore:
    return ReleaseStore.at(tmp_path).initialize()


@pytest.fixture
def publish_release(store: ReleaseStore) -> Publisher:
    """Publish one release into the per-test store, with a fixed clock and commit."""

    def _publish(
        release_id: str,
        model: Model,
        *,
        expected_parent: str | None,
        attempt: int = 1,
    ) -> ArchitectureRelease:
        return publish(
            PublicationRequest(
                store=store,
                candidate=ReleaseCandidate(
                    release_id=release_id,
                    model=model,
                    source_bundle=source_bundle(
                        source_id="examples/minimal/model.yaml", text=EXAMPLE.read_text()
                    ),
                ),
                expected_parent=expected_parent,
                attempt=attempt,
                now=lambda: MOMENT,
                generator_commit="abc1234",
            )
        )

    return _publish


def rename_first_element(model: Model, new_name: str) -> Model:
    """A change that moves `elements` and nothing else."""
    victim = model.elements[0]
    return model.model_validate(
        dict(model)
        | {
            "elements": tuple(
                element.model_validate(dict(element) | {"name": new_name})
                if element.element_id == victim.element_id
                else element
                for element in model.elements
            )
        }
    )
