"""Reading authoring sources (CORE-14, CORE-17, CORE-18).

`parse_source` is the one way YAML becomes model input: the forbidden-construct pre-pass, then
one `compose` under the profile, then the node walk that yields plain data and the SourceMap.
Nothing here constructs a round-trip tree; the editor composes its own when it needs one.

The JSON detour is required, not incidental. Under `strict=True`, Python-mode validation rejects
a plain string where a `StrEnum` member is expected and collapses a `list` supplied to a
`tuple[...]` field to a single error at the field. `model_validate_json` accepts the authored
strings and reports the full location of every nested error, which is what the SourceMap is
keyed by.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

import ruamel.yaml
from ruamel.yaml.composer import ComposerError, MaxDepthExceededError
from ruamel.yaml.error import MarkedYAMLError

from architecture_toolkit.domain.authoring.errors import AuthoringError
from architecture_toolkit.domain.authoring.plain import Plain, build_plain
from architecture_toolkit.domain.authoring.prepass import check_events
from architecture_toolkit.domain.authoring.profile import (
    AUTHORING_PROFILE_VERSION,
    MAX_DEPTH,
    make_yaml,
)
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.source import SourceLocation, SourceMap

__all__ = ["LoadedSource", "YamlSourceLoader", "load_model_text", "parse_model", "parse_source"]


@dataclass(frozen=True, slots=True)
class LoadedSource:
    """Plain data and its SourceMap. Contains no ruamel object (CORE-17)."""

    source_id: str
    text: str
    data: dict[str, Plain]
    source_map: SourceMap

    def json_text(self) -> str:
        """The authoring payload for `Model.model_validate_json`."""
        return json.dumps(self.data)


def _root_location(source_id: str) -> SourceLocation:
    return SourceLocation(source_id=source_id, semantic_path="", line=1, column=1)


def _syntax(source_id: str, failure: MarkedYAMLError, message: str) -> AuthoringError:
    mark = failure.problem_mark
    return AuthoringError(
        "CORE.YAML.SYNTAX",
        str(failure.problem or message),
        location=SourceLocation(
            source_id=source_id,
            semantic_path="",
            line=None if mark is None else mark.line + 1,
            column=None if mark is None else mark.column + 1,
        ),
    )


def parse_source(text: str, *, source_id: str) -> LoadedSource:
    """Pre-pass, compose, walk. Raises `AuthoringError` with every finding attached."""
    check_events(text, source_id=source_id)
    yaml = make_yaml()
    try:
        node = yaml.compose(text)
    except MaxDepthExceededError as failure:
        error = _syntax(source_id, failure, "nesting is too deep")
        raise AuthoringError(
            "CORE.YAML.DEPTH_EXCEEDED",
            f"nesting deeper than {MAX_DEPTH} collections is not permitted",
            location=error.location,
            context=(("max_depth", str(MAX_DEPTH)),),
        ) from failure
    except ComposerError as failure:
        raise _syntax(source_id, failure, "the document could not be composed") from failure
    if node is None:
        raise AuthoringError(
            "CORE.YAML.NOT_A_MAPPING",
            "the document is empty; the root must be a mapping of model fields",
            location=_root_location(source_id),
        )
    walked = build_plain(node, source_id=source_id, constructor=yaml.constructor)
    document = walked.data.get("model_id")
    root_entry = walked.entries[""]
    source_map = SourceMap(
        source_id=source_id,
        document_id=document if isinstance(document, str) else None,
        source_digest=f"sha256:{sha256(text.encode('utf-8')).hexdigest()}",
        parser_version=str(ruamel.yaml.__version__),
        profile_version=AUTHORING_PROFILE_VERSION,
        root=root_entry.value,
        entries=MappingProxyType(walked.entries),
        identity_paths=MappingProxyType(walked.identity_paths),
        record_paths=MappingProxyType(walked.record_paths),
    )
    return LoadedSource(source_id=source_id, text=text, data=walked.data, source_map=source_map)


def parse_model(loaded: LoadedSource) -> Model:
    """Strict validation through the JSON path. A `ValidationError` propagates unchanged."""
    return Model.model_validate_json(loaded.json_text())


def load_model_text(text: str, *, source_id: str) -> tuple[Model, SourceMap]:
    loaded = parse_source(text, source_id=source_id)
    return parse_model(loaded), loaded.source_map


class YamlSourceLoader:
    """The `SourceLoader` implementation: a source ID is a path under `root`."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def load(self, source_id: str) -> LoadedSource:
        text = (self._root / source_id).read_text(encoding="utf-8")
        return parse_source(text, source_id=source_id)
