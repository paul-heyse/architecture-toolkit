import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from ruamel.yaml import YAML

from architecture_toolkit.domain.model import Model


def sample():
    return YAML(typ="safe").load(Path("examples/minimal/model.yaml").read_text())


def test_rejects_dangling_endpoint():
    raw = sample()
    raw["relationships"][0]["target_element_id"] = "missing"
    with pytest.raises(ValidationError, match="unresolved endpoint"):
        Model.model_validate_json(json.dumps(raw))


@given(st.text(min_size=1).filter(lambda x: bool(x.strip())))
def test_rename_preserves_identity(name):
    model = Model.model_validate_json(json.dumps(sample()))
    changed = model.elements[0].model_copy(update={"name": name})
    assert changed.element_id == model.elements[0].element_id


def test_parallel_relations_and_manual_process_are_preserved():
    raw = sample()
    raw["relationships"].append({**raw["relationships"][0], "relationship_id": "parallel"})
    model = Model.model_validate_json(json.dumps(raw))
    assert len(model.relationships) == 7
    assert model.elements[1].status.technical_qualification == "not_qualified"
