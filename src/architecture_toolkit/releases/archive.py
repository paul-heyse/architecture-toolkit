"""Self-contained milestone archives (DATA-25).

> Important architecture baselines must remain readable without depending forever on the current
> state of one live Delta directory.
> — `ARCH-TOOL-DATA-001` §5F

That sentence decides the format. An archive that referenced the live store would be a bookmark,
not an archive, so the tables are written as **complete Parquet snapshots** rather than as Delta
pointers: Parquet preserves the declared schema and field metadata exactly — measured — and needs
no transaction log, no retention policy and no library that understands one.

The contents are §5F's list: the manifest, complete Parquet snapshots, the applicable schemas, the
permitted source snapshots, the semantic change and validation reports, and generated outputs.
`outputs/` ships **empty**. W8 (PROJ-41) fills it, and `reference/plan-waves.json` records that as
an extension rather than a change, which is only true because the directory and its index entry
exist now.

`ARCHIVE.json` digests every file it lists. An archive whose contents cannot be checked against
anything is a directory of files somebody hopes are the right ones.
"""

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from architecture_toolkit.contracts import SCHEMA_FAMILIES
from architecture_toolkit.domain.identifiers import TableId
from architecture_toolkit.releases.errors import ArchiveError
from architecture_toolkit.releases.manifest import ArchitectureRelease
from architecture_toolkit.releases.provenance import digest_bytes
from architecture_toolkit.releases.reader import read_table_set
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage.digests import canonical_table

__all__ = ["ARCHIVE_INDEX", "ArchiveResult", "verify_archive", "write_archive"]

ARCHIVE_INDEX = "ARCHIVE.json"
_TABLES = "tables"
_SCHEMAS = "schemas"
_SOURCES = "sources"
_REPORTS = "reports"
_OUTPUTS = "outputs"


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    """Where the archive is and what it holds, by relative path and digest."""

    release_id: str
    root: Path
    contents: Mapping[str, str]

    @property
    def table_count(self) -> int:
        return sum(1 for name in self.contents if name.startswith(f"{_TABLES}/"))


def write_archive(
    store: ReleaseStore, manifest: ArchitectureRelease, destination: Path | None = None
) -> ArchiveResult:
    """Export one release as a self-contained bundle.

    Tables are written in canonical form — declared types, one chunk, key order, no metadata —
    so two archives of the same release are byte-identical. An archive that differed run to run
    could not be used to check anything against anything.
    """
    root = destination if destination is not None else store.archives_root / manifest.release_id
    if root.exists() and any(root.iterdir()):
        message = f"{root} is not empty; an archive is written once, like the release it holds"
        raise ArchiveError(message)

    for name in (_TABLES, _SCHEMAS, _SOURCES, _REPORTS, _OUTPUTS):
        (root / name).mkdir(parents=True, exist_ok=True)

    contents: dict[str, str] = {}
    contents["manifest.json"] = _write_text(
        root / "manifest.json", manifest.model_dump_json(indent=2) + "\n"
    )

    table_set = read_table_set(store, manifest)
    for table_id in (ref.table_id for ref in manifest.tables):
        contents[f"{_TABLES}/{table_id}.parquet"] = _write_table(
            root / _TABLES / f"{table_id}.parquet", table_id, table_set[table_id]
        )

    for family in SCHEMA_FAMILIES:
        source = Path(family.path)
        if source.is_file():
            contents[f"{_SCHEMAS}/{source.name}"] = _write_text(
                root / _SCHEMAS / source.name, source.read_text(encoding="utf-8")
            )

    report = store.artifact_dir(manifest.release_id) / "validation-report.json"
    if report.is_file():
        contents[f"{_REPORTS}/{report.name}"] = _write_text(
            root / _REPORTS / report.name, report.read_text(encoding="utf-8")
        )

    snapshot = manifest.source_bundle.snapshot_path
    if snapshot is not None and Path(snapshot).is_file():
        target = root / _SOURCES / Path(snapshot).name
        shutil.copyfile(snapshot, target)
        contents[f"{_SOURCES}/{target.name}"] = digest_bytes(target.read_bytes())

    index = {
        "archive_version": 1,
        "release_id": manifest.release_id,
        "model_id": manifest.model_id,
        "model_digest": manifest.model_digest,
        "storage_schema_version": manifest.generator.storage_schema_version,
        "hash_algorithm_version": manifest.generator.hash_algorithm_version,
        # Declared and empty. W8 fills it; the entry existing now is what makes that an extension
        # rather than a format change on every archive already written.
        "outputs": [],
        "contents": dict(sorted(contents.items())),
    }
    (root / ARCHIVE_INDEX).write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return ArchiveResult(release_id=manifest.release_id, root=root, contents=contents)


def verify_archive(root: Path) -> tuple[str, ...]:
    """Every file whose digest no longer matches the index. Empty means intact."""
    index_path = root / ARCHIVE_INDEX
    if not index_path.is_file():
        message = f"{root} holds no {ARCHIVE_INDEX}"
        raise ArchiveError(message)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    contents: Mapping[str, str] = index["contents"]
    return tuple(
        sorted(
            name
            for name, digest in contents.items()
            if not (root / name).is_file() or digest_bytes((root / name).read_bytes()) != digest
        )
    )


def _write_text(path: Path, payload: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return digest_bytes(payload.encode("utf-8"))


def _write_table(path: Path, table_id: TableId, table: object) -> str:
    pq.write_table(canonical_table(table_id, table), path)
    return digest_bytes(path.read_bytes())
