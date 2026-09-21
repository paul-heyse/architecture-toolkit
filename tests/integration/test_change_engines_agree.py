"""DataFusion and the semantic digest answer the same question the same way (DATA-26, DATA-57).

The W5 hard gate says DataFusion and NetworkX read the same release. This is that gate turned
around: where the query engine and `domain/semantics.py` are asked the *same* question — which
identities were added, removed or changed — they must give the same answer. That is what would
drift first, because the engine reads a stamped `content_hash` column while the digest recomputes
one, and a change to normalization that forgot to restamp would separate them silently.

The narrative itself is computed from models, never from the engine: DATA-38 previews a diff before
the candidate is published, so a release-scoped engine cannot be its source. The recipe is a
cross-check, which is the same standing `ARCH-TOOL-DATA-001` §11H gives the Delta change feed.
"""

import pytest

from architecture_toolkit.changes.diff import model_changes
from architecture_toolkit.changes.releases import (
    diff_releases,
    engine_identity_delta,
    identity_disagreements,
)
from architecture_toolkit.domain.model import Model, Relationship
from architecture_toolkit.domain.semantics import SemanticDelta, semantic_delta
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.store import ReleaseStore
from tests.integration.conftest import Publisher, rename_first_element


def without_relationship(model: Model, relationship_id: str) -> Model:
    """Drop one relationship by id, not by position.

    `rel-3` rather than `relationships[0]`: since W7a the example carries a view, and `rel-1` is
    one of its members — so removing the first relationship leaves a view naming an object that
    does not exist, which `validation/rules/views.py` correctly refuses. Naming the relationship
    keeps the test about what it is about, and says why the choice is not arbitrary.
    """
    return model.model_validate(
        dict(model)
        | {
            "relationships": tuple(
                relation
                for relation in model.relationships
                if relation.relationship_id != relationship_id
            )
        }
    )


@pytest.mark.integration
@pytest.mark.requirement("DATA-26", "DATA-57")
def test_the_engine_and_the_digest_agree_about_a_rename(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    base = publish_release("rel-0001", example_model, expected_parent=None)
    candidate = publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )

    assert identity_disagreements(store, base, candidate) == ()

    engine = engine_identity_delta(store, base, candidate)
    assert engine["elements"]["changed"] == (example_model.elements[0].element_id,)
    assert engine["elements"]["added"] == ()
    assert engine["relationships"]["changed"] == ()


@pytest.mark.integration
@pytest.mark.requirement("DATA-26", "DATA-57")
def test_the_engine_and_the_digest_agree_about_an_addition_and_a_removal(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Three answers, not one: the `CASE` arms are only exercised by a case that reaches them."""
    base = publish_release("rel-0001", example_model, expected_parent=None)
    extra = Relationship(
        relationship_id="rel-99",
        model_id=example_model.model_id,
        relationship_type_id="depends_on",
        source_element_id="system-1",
        target_element_id="component-1",
    )
    dropped = without_relationship(example_model, "rel-3")
    widened = dropped.model_validate(
        dict(dropped) | {"relationships": (*dropped.relationships, extra)}
    )
    candidate = publish_release("rel-0002", widened, expected_parent="rel-0001")

    assert identity_disagreements(store, base, candidate) == ()

    engine = engine_identity_delta(store, base, candidate)
    assert engine["relationships"]["added"] == ("rel-99",)
    assert engine["relationships"]["removed"] == ("rel-3",)
    assert engine["relationships"]["changed"] == ()


@pytest.mark.integration
@pytest.mark.requirement("DATA-26", "DATA-57")
def test_the_cross_check_catches_a_disagreement_it_is_given(
    store: ReleaseStore,
    example_model: Model,
    publish_release: Publisher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A comparison that can only ever say "they agree" is worth nothing.

    The two sides agree by construction on any honest input — the engine reads the `content_hash`
    W2 stamped and the oracle recomputes the same function — so a real disagreement has to be
    injected. One side is replaced with a wrong answer, which is the known-bad input this guard is
    required to catch, and the message must name both readings so an operator can tell which
    surface moved.
    """
    base = publish_release("rel-0001", example_model, expected_parent=None)
    candidate = publish_release(
        "rel-0002", rename_first_element(example_model, "Renamed"), expected_parent="rel-0001"
    )
    assert identity_disagreements(store, base, candidate) == ()

    honest = semantic_delta

    def lying(first: Model, second: Model) -> SemanticDelta:
        truth = honest(first, second)
        return truth.model_validate(
            dict(truth)
            | {
                "collections": tuple(
                    delta.model_validate(dict(delta) | {"changed": ("invented-1",)})
                    if delta.collection == "elements"
                    else delta
                    for delta in truth.collections
                )
            }
        )

    monkeypatch.setattr("architecture_toolkit.changes.releases.semantic_delta", lying)

    found = identity_disagreements(store, base, candidate)

    assert len(found) == 1
    assert "elements.changed" in found[0]
    assert "invented-1" in found[0]
    assert example_model.elements[0].element_id in found[0]


@pytest.mark.integration
@pytest.mark.requirement("DATA-26")
def test_a_release_diff_and_a_model_diff_are_the_same_answer(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """One implementation, so a diff cannot mean one thing before publication and another after.

    This is the assertion that keeps the pre-publication preview honest: whatever an operator sees
    from `diff --base --candidate` is exactly what they were shown before they published.
    """
    renamed = rename_first_element(example_model, "Renamed")
    base = publish_release("rel-0001", example_model, expected_parent=None)
    candidate = publish_release("rel-0002", renamed, expected_parent="rel-0001")

    from_releases = diff_releases(store, base, candidate)
    from_models = model_changes(read_model(store, base), read_model(store, candidate))

    assert from_releases == from_models
    assert from_releases.narrative
