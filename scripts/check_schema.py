"""Fail on schema drift; intentional updates use architecture schema > schemas/model.schema.json."""

import json
from pathlib import Path

from architecture_toolkit.domain.model import Model

root = Path(__file__).resolve().parents[1]
if json.loads((root / "schemas/model.schema.json").read_text()) != Model.model_json_schema():
    raise SystemExit("Authoring schema snapshot is stale")
print("Authoring schema snapshot matches")
