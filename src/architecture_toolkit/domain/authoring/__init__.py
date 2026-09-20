"""The YAML authoring adapter (CORE-14..CORE-20).

The only package that imports ruamel.yaml. `rules/ruamel-only-in-authoring.yml` enforces that
structurally and `tests/unit/test_layering.py` proves the rule's exclusion glob; the runtime half
of CORE-17 is that nothing this package returns is a ruamel type.

Reading: `parse_source` -> `LoadedSource` (plain data plus a `SourceMap`) -> `parse_model`.
Editing: `apply_change_set_to_source`, which rewrites the presentation tree and reparses through
the same loader. Neither imports `validation/`; parse failures are `AuthoringError`s that
`validation.normalize.normalize_authoring_error` turns into diagnostics.
"""

from architecture_toolkit.domain.authoring.editing import (
    SourceEditError,
    SourceEditResult,
    apply_change_set_to_source,
)
from architecture_toolkit.domain.authoring.errors import AUTHORING_CODES, AuthoringError
from architecture_toolkit.domain.authoring.loader import (
    LoadedSource,
    YamlSourceLoader,
    load_model_text,
    parse_model,
    parse_source,
)
from architecture_toolkit.domain.authoring.profile import (
    AUTHORING_PROFILE_VERSION,
    MAX_DEPTH,
    AuthoringProfile,
)
from architecture_toolkit.domain.authoring.render import render_model_text, render_record

__all__ = [
    "AUTHORING_CODES",
    "AUTHORING_PROFILE_VERSION",
    "MAX_DEPTH",
    "AuthoringError",
    "AuthoringProfile",
    "LoadedSource",
    "SourceEditError",
    "SourceEditResult",
    "YamlSourceLoader",
    "apply_change_set_to_source",
    "load_model_text",
    "parse_model",
    "parse_source",
    "render_model_text",
    "render_record",
]
