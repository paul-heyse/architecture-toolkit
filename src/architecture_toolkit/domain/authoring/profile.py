"""The one configured ruamel.yaml factory (CORE-14).

`ARCH-TOOL-CORE-001` §5B: round-trip mode, YAML 1.2, quote preservation, explicit indentation,
width and output settings, an explicit maximum depth, duplicate keys as errors and no unsafe
constructors. Every value is a named constant so the SourceMap can record which profile parsed
a document and a later change is a profile version, not a drift.

**A fresh instance per load.** ruamel's composer keeps its depth counter on the instance and it
was measured not resetting between loads, so a shared instance would reject a shallow document
after a deep one. `make_yaml()` is cheap and is the only constructor call in the package.

**YAML 1.2 is the default and `version` stays unset.** Setting `yaml.version` makes every dump
emit a `%YAML 1.2` directive; the pre-pass rejects a `%YAML 1.1` directive instead, which is the
same guarantee without rewriting every file.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final

from ruamel.yaml import YAML

__all__ = [
    "AUTHORING_PROFILE_VERSION",
    "CORE_SCHEMA_TAGS",
    "INDENT",
    "MAX_DEPTH",
    "PERMITTED_VERSIONS",
    "PYTHON_TAG_PREFIX",
    "WIDTH",
    "AuthoringProfile",
    "dump_text",
    "make_yaml",
]

AUTHORING_PROFILE_VERSION: Final[str] = "1"

# Sixteen nested collections. The deepest domain path is seven (model > elements > item > detail
# > fields > item > key_membership), so this bounds a hostile document without constraining an
# authored one. The pre-pass counts collections and reports the position; ruamel's composer
# counts *nodes*, scalars included, so a scalar leaf at collection depth sixteen is node depth
# seventeen. `make_yaml` sets the composer bound one higher so the two agree exactly.
MAX_DEPTH: Final[int] = 16

# Matches `pyproject.toml`'s Ruff line length, so authored and regenerated files wrap alike.
WIDTH: Final[int] = 100

# mapping, sequence, offset — `  - key:` under a key, which is the example fixture's style and
# the only setting under which a block-style document dumps back byte-identically.
INDENT: Final[tuple[int, int, int]] = (2, 4, 2)

PERMITTED_VERSIONS: Final[frozenset[tuple[int, int] | None]] = frozenset({None, (1, 2)})

# The YAML 1.2 core schema. `!!timestamp`, `!!binary`, `!!set` and `!!omap` are outside it and are
# reported as custom tags; a plain `2024-01-01` is read as a string.
CORE_SCHEMA_TAGS: Final[frozenset[str]] = frozenset(
    f"tag:yaml.org,2002:{name}" for name in ("str", "int", "float", "bool", "null", "map", "seq")
)
PYTHON_TAG_PREFIX: Final[str] = "tag:yaml.org,2002:python/"


@dataclass(frozen=True, slots=True)
class AuthoringProfile:
    """What parsed a document. Recorded on the SourceMap; never architecture semantics."""

    profile_version: str = AUTHORING_PROFILE_VERSION
    yaml_version: tuple[int, int] = (1, 2)
    max_depth: int = MAX_DEPTH
    width: int = WIDTH
    indent: tuple[int, int, int] = INDENT
    preserve_quotes: bool = True


PROFILE: Final[AuthoringProfile] = AuthoringProfile()


def make_yaml() -> YAML:
    """A fresh, fully configured round-trip instance. See the module docstring for why fresh."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    mapping, sequence, offset = INDENT
    yaml.indent(mapping=mapping, sequence=sequence, offset=offset)
    yaml.width = WIDTH
    yaml.max_depth = MAX_DEPTH + 1
    yaml.allow_duplicate_keys = False
    yaml.default_flow_style = False
    yaml.explicit_start = False
    yaml.explicit_end = False
    yaml.sort_base_mapping_type_on_output = False
    yaml.allow_unicode = True
    return yaml


def dump_text(tree: object) -> str:
    """Serialize a presentation tree with the profile's output settings."""
    buffer = io.StringIO()
    make_yaml().dump(tree, buffer)
    return buffer.getvalue()
