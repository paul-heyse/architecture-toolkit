"""Which standards schemas exist, what each imports, and how a reference names it (CORE-41).

Facts about the standards, not about a filesystem. `PinnedSchemas` needs a path per file and a
digest per file, and both of those are properties of an installation — `.tools/` in this
repository, somewhere else in a packaged one. What is *not* installation-specific is the set of
files a standard is made of, which one is the entry point, and which absolute URIs a schema
imports by URL rather than by sibling filename. Those live here so a caller assembles a pinned
set from a lock file and a root directory without also having to know that `archimate3_Model.xsd`
reaches outside its own directory.

**The ArchiMate set is why aliases exist.** `archimate3_Model.xsd` imports
`http://www.w3.org/2001/xml.xsd` — an absolute remote URI, not a sibling. Measured: without a
resolver serving pinned bytes for it, the schema does not build at all, because it uses
`xml:lang` and libxml2 cannot resolve the attribute group. The W3C serves that file under both
`http` and `https`, and a schema author may have written either, so both spellings alias to the
one pinned copy.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

from architecture_toolkit.projections.errors import ProjectionError
from architecture_toolkit.projections.xml import PinnedSchemas

__all__ = ["SCHEMA_SETS", "SchemaSet", "pinned_set"]


@dataclass(frozen=True, slots=True)
class SchemaSet:
    """One standard's pinned schema files, and how they are reached."""

    standard: str
    entry: str
    """The file a validator starts from."""

    lock_prefix: str
    """The `tools.lock.json` artifact id prefix that names this set's files."""

    aliases: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """Absolute URIs a member imports by URL, mapped to the pinned file that answers them."""

    extra_lock_prefixes: Sequence[str] = ()
    """Other lock prefixes whose files this set needs — the W3C `xml.xsd` for ArchiMate."""

    @property
    def prefixes(self) -> tuple[str, ...]:
        return (self.lock_prefix, *self.extra_lock_prefixes)


_W3C_XML: Final[Mapping[str, str]] = MappingProxyType(
    {
        "http://www.w3.org/2001/xml.xsd": "xml.xsd",
        "https://www.w3.org/2001/xml.xsd": "xml.xsd",
    }
)

SCHEMA_SETS: Final[Mapping[str, SchemaSet]] = MappingProxyType(
    {
        "bpmn": SchemaSet(
            standard="OMG BPMN 2.0.2",
            entry="BPMN20.xsd",
            lock_prefix="bpmn-",
        ),
        "archimate": SchemaSet(
            standard="Open Group ArchiMate 3.1 Model Exchange",
            entry="archimate3_Model.xsd",
            lock_prefix="archimate-",
            aliases=_W3C_XML,
            extra_lock_prefixes=("w3c-",),
        ),
    }
)
"""The two sets W7b's generators will validate against. Declared here, used from W7b onward.

`archimate3_View.xsd` and `archimate3_Diagram.xsd` are pinned and not the entry point: PROJ-18
defers exchange-format diagram geometry, so the baseline artifact is model-level. They are pinned
now anyway, because pinning a file costs a lock entry and discovering later that a needed schema
was never reviewed costs a wave.
"""


def pinned_set(name: str, *, root: Path, lock: Mapping[str, object]) -> PinnedSchemas:
    """Assemble a `PinnedSchemas` for one standard from a vendor root and a parsed lock file.

    `root` is where `bootstrap_tools.py` put the files — `.tools/` in this repository. The caller
    supplies it because `src/` has no repository around it once the toolkit is installed.
    """
    declared = SCHEMA_SETS.get(name)
    if declared is None:
        message = f"unknown schema set {name!r}; declared sets are {sorted(SCHEMA_SETS)}"
        raise ProjectionError(message)

    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, list):
        message = "the tools lock has no artifact list"
        raise ProjectionError(message)

    files: dict[str, Path] = {}
    digests: dict[str, str] = {}
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id", ""))
        if not identifier.startswith(declared.prefixes):
            continue
        relative = str(item["path"])
        name_only = Path(relative).name
        files[name_only] = (root / relative).resolve()
        digests[name_only] = str(item["sha256"])

    if declared.entry not in files:
        message = f"{name}: the lock does not pin the entry schema {declared.entry!r}"
        raise ProjectionError(message)
    return PinnedSchemas(files=files, digests=digests, aliases=declared.aliases)
