"""The on-disk release store, and the pointer that makes a release current (DATA-23, DATA-24).

The layout is deliberately boring, because the interesting property is a filesystem one:

```text
<root>/tables/<table_id>/          Delta tables, one directory per table id
<root>/releases/<release_id>.json  immutable manifests
<root>/artifacts/<release_id>/     validation and change reports
<root>/CURRENT                     the pointer; replaced atomically
<root>/publication.lock            held only while publishing
<root>/archives/<release_id>/      milestone exports
```

**`CURRENT` is the commit point of the whole protocol.** A manifest existing in `releases/` does
not make it current — the pointer move does, and that move is a single `os.replace`, which is
atomic within a filesystem. So a crash at any earlier step leaves manifests and Delta versions
lying around that nothing references, which DATA-24 explicitly permits, and leaves the previous
release resolving exactly as before, which DATA-24 explicitly requires.

The store never resolves a table by convention or guesses a location. `table_location` is a pure
function of the root and the table id, and a manifest's `TableRef.uri` is relative to the root, so
a store that is copied elsewhere still reads.

**Live Delta directories stay host-local.** The default root is under `.runtime/`, which
`.gitignore` ignores and `scripts/check_boundaries.py` refuses to let anyone commit.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.releases.errors import ReleaseError, UnknownReleaseError
from architecture_toolkit.releases.manifest import ArchitectureRelease

__all__ = [
    "CURRENT_POINTER",
    "DEFAULT_STORE_ROOT",
    "ReleaseStore",
]

CURRENT_POINTER: Final[str] = "CURRENT"
DEFAULT_STORE_ROOT: Final[Path] = Path(".runtime") / "releases"
"""Under the ignored runtime directory. Never a synced folder; never committed."""

_TABLES = "tables"
_RELEASES = "releases"
_ARTIFACTS = "artifacts"
_ARCHIVES = "archives"
_LOCK = "publication.lock"


@dataclass(frozen=True, slots=True)
class ReleaseStore:
    """Where releases live. A value, not a session: it opens nothing and holds no handles."""

    root: Path

    @classmethod
    def at(cls, root: Path | str = DEFAULT_STORE_ROOT) -> ReleaseStore:
        return cls(root=Path(root))

    # -- layout ---------------------------------------------------------------------------------

    @property
    def tables_root(self) -> Path:
        return self.root / _TABLES

    @property
    def releases_root(self) -> Path:
        return self.root / _RELEASES

    @property
    def artifacts_root(self) -> Path:
        return self.root / _ARTIFACTS

    @property
    def archives_root(self) -> Path:
        return self.root / _ARCHIVES

    @property
    def lock_path(self) -> Path:
        return self.root / _LOCK

    @property
    def pointer_path(self) -> Path:
        return self.root / CURRENT_POINTER

    def table_uri(self, table_id: TableId) -> str:
        """The manifest-relative uri for a table. Pure; the store need not exist."""
        return f"{_TABLES}/{table_id}"

    def table_location(self, table_id: TableId) -> Path:
        return self.tables_root / table_id

    def resolve(self, uri: str) -> Path:
        """A manifest's relative uri as a path in *this* store, which may not be where it was
        written. That is the point of keeping uris relative."""
        return self.root / uri

    def manifest_path(self, release_id: str) -> Path:
        return self.releases_root / f"{release_id}.json"

    def artifact_dir(self, release_id: str) -> Path:
        return self.artifacts_root / release_id

    def initialize(self) -> ReleaseStore:
        """Create the directory skeleton. Idempotent; creating a store twice is not an error."""
        for path in (self.tables_root, self.releases_root, self.artifacts_root, self.archives_root):
            path.mkdir(parents=True, exist_ok=True)
        return self

    # -- manifests ------------------------------------------------------------------------------

    def write_manifest(self, manifest: ArchitectureRelease) -> Path:
        """Write a manifest. **Refuses to overwrite** — a published manifest is immutable.

        This is the only place that immutability can be enforced, because nothing downstream can
        tell a rewritten manifest from an original one.
        """
        path = self.manifest_path(manifest.release_id)
        if path.exists():
            message = (
                f"release {manifest.release_id!r} is already published; manifests are immutable"
            )
            raise ReleaseError(message)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return path

    def read_manifest(self, release_id: str) -> ArchitectureRelease:
        path = self.manifest_path(release_id)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise UnknownReleaseError(release_id) from None
        return ArchitectureRelease.model_validate_json(text)

    def has_manifest(self, release_id: str) -> bool:
        return self.manifest_path(release_id).is_file()

    def release_ids(self) -> tuple[str, ...]:
        """Every published release id, sorted. Sorted rather than by mtime: a filesystem
        timestamp is not provenance, and the manifest carries `published_at` if order matters."""
        if not self.releases_root.is_dir():
            return ()
        return tuple(sorted(path.stem for path in self.releases_root.glob("*.json")))

    def iter_manifests(self) -> Iterator[ArchitectureRelease]:
        """Every retained manifest. The input to the DATA-58 retention computation."""
        for release_id in self.release_ids():
            yield self.read_manifest(release_id)

    # -- the current pointer --------------------------------------------------------------------

    def current_id(self) -> str | None:
        """The current release id, or `None` for an empty store."""
        try:
            raw = self.pointer_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        pointer = json.loads(raw)
        release_id = pointer["release_id"]
        if not isinstance(release_id, str):
            message = f"{self.pointer_path} holds a non-string release_id"
            raise ReleaseError(message)
        return release_id

    def current(self) -> ArchitectureRelease | None:
        release_id = self.current_id()
        return None if release_id is None else self.read_manifest(release_id)

    def set_current(self, manifest: ArchitectureRelease) -> None:
        """Move the pointer atomically. **The commit point of the publication protocol.**

        Written to a sibling temporary file and `os.replace`d, which is atomic within a
        filesystem: a reader sees either the old pointer or the new one, never a truncated file.
        The manifest must already be published — pointing at one that does not exist would be the
        partial state DATA-24 forbids.
        """
        if not self.has_manifest(manifest.release_id):
            message = f"cannot make {manifest.release_id!r} current: its manifest is not published"
            raise ReleaseError(message)
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"release_id": manifest.release_id, "model_digest": manifest.model_digest}, indent=2
        )
        staged = self.pointer_path.with_suffix(".staged")
        staged.write_text(payload + "\n", encoding="utf-8")
        # `Path.replace` is `os.replace`: one atomic rename, so a reader sees the old pointer
        # or the new one and never a half-written file.
        staged.replace(self.pointer_path)
