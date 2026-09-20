import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from ruamel.yaml import YAML

from architecture_toolkit.domain.model import Model


def sample() -> dict[str, Any]:
    return YAML(typ="safe").load(Path("examples/minimal/model.yaml").read_text())


@pytest.mark.unit
@pytest.mark.requirement("CORE-07", "DATA-03")
def test_rejects_dangling_endpoint() -> None:
    raw = sample()
    raw["relationships"][0]["target_element_id"] = "missing"
    with pytest.raises(ValidationError, match="unresolved endpoint"):
        Model.model_validate_json(json.dumps(raw))


@pytest.mark.property
@pytest.mark.requirement("CORE-10", "DATA-04")
@given(st.text(min_size=1).filter(lambda x: bool(x.strip())))
def test_rename_preserves_identity(name: str) -> None:
    model = Model.model_validate_json(json.dumps(sample()))
    changed = model.elements[0].model_copy(update={"name": name})
    assert changed.element_id == model.elements[0].element_id


@pytest.mark.unit
@pytest.mark.requirement("DATA-05", "DATA-29", "DATA-41")
def test_parallel_relations_and_manual_process_are_preserved() -> None:
    raw = sample()
    raw["relationships"].append({**raw["relationships"][0], "relationship_id": "parallel"})
    model = Model.model_validate_json(json.dumps(raw))
    assert len(model.relationships) == 7
    assert model.elements[1].status.technical_qualification == "not_qualified"
