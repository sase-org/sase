"""Explicit artifact-file storage and JSONL index operations."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sase.core.artifact_file_helpers import (
    artifact_file_association_from_metadata,
    artifact_file_id,
    artifact_file_mime_type,
    file_created_at,
    hash_file,
    hash_text,
    now_iso,
    safe_segment,
)
from sase.core.artifact_file_query_facade import (
    ArtifactFileSourceIdentity,
    query_artifact_file_associations,
)
from sase.core.artifact_file_types import (
    ARTIFACT_FILE_INDEX_SCHEMA_VERSION,
    ARTIFACT_FILE_INDEX_SUPPORTED_SCHEMA_VERSIONS,
    ArtifactFile,
    ArtifactFileAssociation,
    ArtifactFileKind,
    _JSONL_INDEX_NAME,
    _LOCK_NAME,
    artifact_file_from_dict,
    artifact_file_to_dict,
    artifact_file_association_from_dir,
    coerce_artifact_file_kind,
    default_artifact_files_index_path,
    default_artifact_files_root,
    infer_artifact_file_kind,
)

_ASSOCIATION_CACHE_MAX_ENTRIES = 128
_ASSOCIATION_CACHE_MAX_ROWS = 1024
_ASSOCIATION_CACHE_MAX_BYTES = 256 * 1024
_MIN_REREAD_INTERVAL_S = 0.5
_AssociationCacheKey = tuple[str, str, str | None, str | None, bool]
_SourceIdentity = tuple[int, int, int, int, bool]


@dataclass(frozen=True)
class _AssociationCacheEntry:
    rows: tuple[ArtifactFile, ...]
    identity: _SourceIdentity
    last_read_monotonic: float


_artifact_file_association_cache_lock = threading.RLock()
# Targeted answers keyed by resolved index path and association. Values are
# bounded by row count; oversized matching sets are returned uncached.
_artifact_file_association_cache: OrderedDict[
    _AssociationCacheKey, _AssociationCacheEntry
] = OrderedDict()


def store_explicit_artifact_file(
    source_path: Path | str,
    agent_artifacts_dir: Path | str,
    *,
    label: str | None = None,
    kind: ArtifactFileKind | str | None = None,
    artifact_files_root: Path | str | None = None,
    index_path: Path | str | None = None,
    move: bool = False,
    created_at: str | None = None,
) -> ArtifactFile:
    """Store an explicit artifact file and upsert its persistent association.

    By default the source file is copied. Pass ``move=True`` when called from a
    command that should relocate the file into ``~/.sase/artifacts/``.
    """

    source = Path(source_path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(str(source))

    root = (
        Path(artifact_files_root).expanduser()
        if artifact_files_root
        else default_artifact_files_root()
    )
    idx = Path(index_path).expanduser() if index_path else root / _JSONL_INDEX_NAME
    association = artifact_file_association_from_metadata(agent_artifacts_dir)
    artifact_file_kind = (
        coerce_artifact_file_kind(kind)
        if kind is not None
        else infer_artifact_file_kind(source)
    )
    stored_path, sha256 = _store_file(source, root, association, move=move)
    artifact_file = ArtifactFile(
        id=artifact_file_id("explicit", association, stored_path, label or source.name),
        label=label or source.name,
        kind=artifact_file_kind,
        path=str(stored_path),
        source_path=str(source),
        created_at=created_at or now_iso(),
        agent_artifacts_dir=association.agent_artifacts_dir,
        project=association.project,
        workflow=association.workflow,
        raw_timestamp=association.raw_timestamp,
        agent_name=association.agent_name,
        explicit=True,
        sha256=sha256,
        size_bytes=stored_path.stat().st_size,
        mime_type=artifact_file_mime_type(stored_path),
    )
    _upsert_index_row(idx, artifact_file)
    return artifact_file


def store_default_artifact_file(
    source_path: Path | str,
    agent_artifacts_dir: Path | str,
    *,
    label: str | None = None,
    kind: ArtifactFileKind | str | None = None,
    artifact_files_root: Path | str | None = None,
    index_path: Path | str | None = None,
    workspace_dir: str | None = None,
    created_at: str | None = None,
    vcs_repo: str | None = None,
    vcs_sha: str | None = None,
    vcs_relpath: str | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    mime_type: str | None = None,
    artifact_association: ArtifactFileAssociation | None = None,
) -> ArtifactFile | None:
    """Persist an auto-discovered (default) artifact file to the global store.

    Mirrors :func:`store_explicit_artifact_file` but writes ``explicit=False``.
    Byte-backed storage silently skips a missing ``source_path``; reference mode
    accepts one because durable VCS bytes may outlive the original workspace.
    """

    source = Path(source_path).expanduser()
    reference_mode = all((vcs_repo, vcs_sha, vcs_relpath))
    if any((vcs_repo, vcs_sha, vcs_relpath)) and not reference_mode:
        raise ValueError("reference mode requires complete VCS provenance")
    if reference_mode and (sha256 is None or size_bytes is None):
        raise ValueError("reference mode requires precomputed digest and size")
    if not reference_mode and not source.is_file():
        return None

    root = (
        Path(artifact_files_root).expanduser()
        if artifact_files_root
        else default_artifact_files_root()
    )
    idx = Path(index_path).expanduser() if index_path else root / _JSONL_INDEX_NAME
    association = artifact_association or artifact_file_association_from_metadata(
        agent_artifacts_dir
    )
    artifact_file_kind = (
        coerce_artifact_file_kind(kind)
        if kind is not None
        else infer_artifact_file_kind(source)
    )
    stored_path: Path | None
    if reference_mode:
        stored_path = None
    else:
        stored_path, sha256 = _store_file(
            source,
            root,
            association,
            move=False,
            sha256=sha256,
        )
        size_bytes = (
            size_bytes if size_bytes is not None else stored_path.stat().st_size
        )
        mime_type = mime_type or artifact_file_mime_type(stored_path)
    identity_label = label or source.name
    artifact_file = ArtifactFile(
        id=artifact_file_id(
            "default",
            association,
            stored_path,
            identity_label,
            vcs_repo=vcs_repo,
            vcs_relpath=vcs_relpath,
            sha256=sha256,
        ),
        label=identity_label,
        kind=artifact_file_kind,
        path=None if stored_path is None else str(stored_path),
        source_path=str(source),
        workspace_dir=workspace_dir,
        created_at=created_at or file_created_at(source) or now_iso(),
        agent_artifacts_dir=association.agent_artifacts_dir,
        project=association.project,
        workflow=association.workflow,
        raw_timestamp=association.raw_timestamp,
        agent_name=association.agent_name,
        explicit=False,
        sha256=sha256,
        size_bytes=size_bytes,
        mime_type=mime_type or artifact_file_mime_type(source),
        vcs_repo=vcs_repo,
        vcs_sha=vcs_sha,
        vcs_relpath=vcs_relpath,
    )
    _upsert_index_row(idx, artifact_file)
    return artifact_file


def read_artifact_file_index(
    index_path: Path | str | None = None,
) -> tuple[ArtifactFile, ...]:
    """Read all artifact-file rows from the persistent index.

    This is an uncached bulk reader for doctor, retention, and other explicit
    whole-index consumers. Frequent listing paths must use
    :func:`list_indexed_artifact_files` so unmatched rows are never converted
    into Python objects.
    """

    idx = _normalize_index_path(index_path)
    if not idx.exists():
        return ()
    with artifact_file_index_lock(idx, exclusive=False):
        return tuple(_read_index_unlocked(idx))


def list_indexed_artifact_files(
    agent_artifacts_dir: Path | str,
    *,
    index_path: Path | str | None = None,
) -> list[ArtifactFile]:
    """Return all indexed artifact files for one agent run."""

    return _list_associated_artifact_files(
        artifact_file_association_from_dir(agent_artifacts_dir),
        index_path=index_path,
        explicit_only=False,
    )


def list_explicit_artifact_files(
    agent_artifacts_dir: Path | str,
    *,
    index_path: Path | str | None = None,
) -> list[ArtifactFile]:
    """Return explicit artifact files associated with one agent run."""

    return _list_associated_artifact_files(
        artifact_file_association_from_dir(agent_artifacts_dir),
        index_path=index_path,
        explicit_only=True,
    )


def _list_associated_artifact_files(
    association: ArtifactFileAssociation,
    *,
    index_path: Path | str | None,
    explicit_only: bool,
) -> list[ArtifactFile]:
    idx = _normalize_index_path(index_path)
    key = _association_cache_key(idx, association, explicit_only)
    now = time.monotonic()
    cached = _peek_association_cache(key)
    if (
        cached is not None
        and (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
    ):
        return list(cached.rows)

    identity = _index_source_identity(idx)
    if identity[4]:
        _store_association_cache(key, (), identity, now)
        return []

    with artifact_file_index_lock(idx, exclusive=False):
        cached = _peek_association_cache(key)
        now = time.monotonic()
        if (
            cached is not None
            and (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        ):
            _touch_association_cache(key, now)
            return list(cached.rows)
        identity = _index_source_identity(idx)
        if cached is not None and cached.identity == identity:
            _touch_association_cache(key, now)
            return list(cached.rows)
        rows, source = query_artifact_file_associations(
            idx,
            agent_artifacts_dir=association.agent_artifacts_dir,
            project=association.project,
            raw_timestamp=association.raw_timestamp,
            explicit_only=explicit_only,
        )
        frozen = tuple(rows)
        _store_association_cache(
            key, frozen, _source_identity_tuple(source), time.monotonic()
        )
        return list(frozen)


def _store_file(
    source: Path,
    artifact_files_root: Path,
    association: ArtifactFileAssociation,
    *,
    move: bool,
    sha256: str | None = None,
) -> tuple[Path, str]:
    target_dir = (
        artifact_files_root
        / "agents"
        / safe_segment(association.project or "unknown-project")
        / safe_segment(
            association.raw_timestamp or hash_text(association.agent_artifacts_dir)[:12]
        )
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix
    stem = safe_segment(source.stem) or "artifact"
    digest = sha256 or hash_file(source)
    target = target_dir / f"{stem}-{digest[:12]}{suffix}"
    if target.exists():
        if move and source.resolve(strict=False) != target.resolve(strict=False):
            source.unlink()
        return target, digest

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target_dir,
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        shutil.copy2(source, tmp_path)
        os.replace(tmp_path, target)
        if move:
            source.unlink()
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return target, digest


def _upsert_index_row(index_path: Path, artifact_file: ArtifactFile) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_file_index_lock(index_path, exclusive=True):
        rows, preserved_lines = read_artifact_file_index_document_unlocked(index_path)
        rows_by_id = {row.id: row for row in rows}
        rows_by_id[artifact_file.id] = artifact_file
        write_artifact_file_index_unlocked(
            index_path,
            list(rows_by_id.values()),
            preserved_lines=preserved_lines,
        )


def _read_index_unlocked(index_path: Path) -> list[ArtifactFile]:
    rows, _preserved_lines = read_artifact_file_index_document_unlocked(index_path)
    return rows


def read_artifact_file_index_document_unlocked(
    index_path: Path,
) -> tuple[list[ArtifactFile], list[str]]:
    """Read supported rows and verbatim preserved lines with the lock held."""

    if not index_path.exists():
        return [], []
    rows: list[ArtifactFile] = []
    preserved_lines: list[str] = []
    with index_path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except (json.JSONDecodeError, UnicodeDecodeError):
                preserved_lines.append(line)
                continue
            if not isinstance(data, dict):
                preserved_lines.append(line)
                continue
            try:
                schema_version = int(data.get("schema_version", 0))
            except (TypeError, ValueError):
                preserved_lines.append(line)
                continue
            if schema_version not in ARTIFACT_FILE_INDEX_SUPPORTED_SCHEMA_VERSIONS:
                preserved_lines.append(line)
                continue
            artifact_data = data.get("artifact")
            if isinstance(artifact_data, dict):
                try:
                    rows.append(artifact_file_from_dict(artifact_data))
                except (KeyError, TypeError, ValueError):
                    preserved_lines.append(line)
            else:
                preserved_lines.append(line)
    return rows, preserved_lines


def write_artifact_file_index_unlocked(
    index_path: Path,
    rows: list[ArtifactFile],
    *,
    preserved_lines: list[str] | None = None,
) -> None:
    """Atomically write supported rows and preserved lines with the lock held."""

    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{index_path.name}.",
        suffix=".tmp",
        dir=index_path.parent,
        text=True,
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": ARTIFACT_FILE_INDEX_SCHEMA_VERSION,
                            "artifact": artifact_file_to_dict(row),
                        },
                        sort_keys=True,
                    )
                )
                handle.write("\n")
            for line in preserved_lines or []:
                handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, index_path)
        _invalidate_artifact_file_association_cache(index_path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _normalize_index_path(index_path: Path | str | None) -> Path:
    idx = (
        Path(index_path).expanduser()
        if index_path
        else default_artifact_files_index_path()
    )
    return idx.resolve(strict=False)


def _association_cache_key(
    index_path: Path,
    association: ArtifactFileAssociation,
    explicit_only: bool,
) -> _AssociationCacheKey:
    return (
        str(index_path),
        association.agent_artifacts_dir,
        association.project,
        association.raw_timestamp,
        explicit_only,
    )


def _source_identity_tuple(
    source: ArtifactFileSourceIdentity,
) -> _SourceIdentity:
    return (source.dev, source.ino, source.mtime_ns, source.size, source.missing)


def _index_source_identity(index_path: Path) -> _SourceIdentity:
    try:
        stat = index_path.stat()
    except FileNotFoundError:
        return (0, 0, 0, 0, True)
    except OSError:
        return (0, 0, 0, 0, True)
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size, False)


def _peek_association_cache(
    key: _AssociationCacheKey,
) -> _AssociationCacheEntry | None:
    with _artifact_file_association_cache_lock:
        return _artifact_file_association_cache.get(key)


def _touch_association_cache(key: _AssociationCacheKey, now: float) -> None:
    with _artifact_file_association_cache_lock:
        cached = _artifact_file_association_cache.get(key)
        if cached is None:
            return
        _artifact_file_association_cache[key] = _AssociationCacheEntry(
            rows=cached.rows,
            identity=cached.identity,
            last_read_monotonic=now,
        )
        _artifact_file_association_cache.move_to_end(key)


def _store_association_cache(
    key: _AssociationCacheKey,
    rows: tuple[ArtifactFile, ...],
    identity: _SourceIdentity,
    now: float,
) -> None:
    if (
        len(rows) > _ASSOCIATION_CACHE_MAX_ROWS
        or _estimated_association_bytes(rows) > _ASSOCIATION_CACHE_MAX_BYTES
    ):
        _invalidate_association_cache_key(key)
        return
    with _artifact_file_association_cache_lock:
        _artifact_file_association_cache[key] = _AssociationCacheEntry(
            rows=rows,
            identity=identity,
            last_read_monotonic=now,
        )
        _artifact_file_association_cache.move_to_end(key)
        while len(_artifact_file_association_cache) > _ASSOCIATION_CACHE_MAX_ENTRIES:
            _artifact_file_association_cache.popitem(last=False)


def _estimated_association_bytes(rows: tuple[ArtifactFile, ...]) -> int:
    total = 0
    for row in rows:
        total += 64
        for value in (
            row.id,
            row.label,
            row.path,
            row.source_path,
            row.workspace_dir,
            row.created_at,
            row.agent_artifacts_dir,
            row.project,
            row.workflow,
            row.raw_timestamp,
            row.agent_name,
            row.sha256,
            row.mime_type,
            row.vcs_repo,
            row.vcs_sha,
            row.vcs_relpath,
        ):
            if isinstance(value, str):
                total += len(value)
    return total


def _invalidate_association_cache_key(key: _AssociationCacheKey) -> None:
    with _artifact_file_association_cache_lock:
        _artifact_file_association_cache.pop(key, None)


def _invalidate_artifact_file_association_cache(index_path: Path) -> None:
    resolved = str(index_path.expanduser().resolve(strict=False))
    with _artifact_file_association_cache_lock:
        stale = [key for key in _artifact_file_association_cache if key[0] == resolved]
        for key in stale:
            _artifact_file_association_cache.pop(key, None)


@contextmanager
def artifact_file_index_lock(
    index_path: Path,
    *,
    exclusive: bool,
) -> Iterator[None]:
    """Hold the shared artifact-file index lock."""

    index_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = index_path.parent / _LOCK_NAME
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
