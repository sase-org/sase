"""Explicit agent artifact storage and JSONL index operations."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sase.core.agent_artifact_helpers import (
    artifact_id,
    association_from_metadata,
    hash_file,
    hash_text,
    matches_association,
    now_iso,
    safe_segment,
)
from sase.core.agent_artifact_types import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AgentArtifact,
    AgentArtifactAssociation,
    AgentArtifactKind,
    _JSONL_INDEX_NAME,
    _LOCK_NAME,
    agent_artifact_from_dict,
    agent_artifact_to_dict,
    artifact_association_from_dir,
    coerce_artifact_kind,
    default_agent_artifacts_index_path,
    default_artifacts_root,
    infer_artifact_kind,
)


def store_explicit_agent_artifact(
    source_path: Path | str,
    agent_artifacts_dir: Path | str,
    *,
    label: str | None = None,
    kind: AgentArtifactKind | str | None = None,
    artifacts_root: Path | str | None = None,
    index_path: Path | str | None = None,
    move: bool = False,
    created_at: str | None = None,
) -> AgentArtifact:
    """Store an explicit artifact and upsert its persistent association.

    By default the source file is copied. Pass ``move=True`` when called from a
    command that should relocate the file into ``~/.sase/artifacts/``.
    """

    source = Path(source_path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(str(source))

    root = (
        Path(artifacts_root).expanduser()
        if artifacts_root
        else default_artifacts_root()
    )
    idx = Path(index_path).expanduser() if index_path else root / _JSONL_INDEX_NAME
    association = association_from_metadata(agent_artifacts_dir)
    artifact_kind = (
        coerce_artifact_kind(kind) if kind is not None else infer_artifact_kind(source)
    )
    stored_path = _store_file(source, root, association, move=move)
    artifact = AgentArtifact(
        id=artifact_id("explicit", association, stored_path, label or source.name),
        label=label or source.name,
        kind=artifact_kind,
        path=str(stored_path),
        source_path=str(source),
        created_at=created_at or now_iso(),
        agent_artifacts_dir=association.agent_artifacts_dir,
        project=association.project,
        workflow=association.workflow,
        raw_timestamp=association.raw_timestamp,
        agent_name=association.agent_name,
        explicit=True,
    )
    _upsert_index_row(idx, artifact)
    return artifact


def read_explicit_agent_artifact_index(
    index_path: Path | str | None = None,
) -> list[AgentArtifact]:
    """Read all explicit artifact rows from the persistent index."""

    idx = (
        Path(index_path).expanduser()
        if index_path
        else default_agent_artifacts_index_path()
    )
    if not idx.exists():
        return []
    with _index_lock(idx, exclusive=False):
        return _read_index_unlocked(idx)


def list_explicit_agent_artifacts(
    agent_artifacts_dir: Path | str,
    *,
    index_path: Path | str | None = None,
) -> list[AgentArtifact]:
    """Return explicit artifacts associated with one agent run."""

    association = artifact_association_from_dir(agent_artifacts_dir)
    rows = read_explicit_agent_artifact_index(index_path)
    return [row for row in rows if matches_association(row, association)]


def _store_file(
    source: Path,
    artifacts_root: Path,
    association: AgentArtifactAssociation,
    *,
    move: bool,
) -> Path:
    target_dir = (
        artifacts_root
        / "agents"
        / safe_segment(association.project or "unknown-project")
        / safe_segment(
            association.raw_timestamp or hash_text(association.agent_artifacts_dir)[:12]
        )
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix
    stem = safe_segment(source.stem) or "artifact"
    digest = hash_file(source)[:12]
    target = target_dir / f"{stem}-{digest}{suffix}"
    if target.exists():
        if move and source.resolve(strict=False) != target.resolve(strict=False):
            source.unlink()
        return target

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
    return target


def _upsert_index_row(index_path: Path, artifact: AgentArtifact) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with _index_lock(index_path, exclusive=True):
        rows = _read_index_unlocked(index_path)
        rows_by_id = {row.id: row for row in rows}
        rows_by_id[artifact.id] = artifact
        _write_index_unlocked(index_path, list(rows_by_id.values()))


def _read_index_unlocked(index_path: Path) -> list[AgentArtifact]:
    if not index_path.exists():
        return []
    rows: list[AgentArtifact] = []
    with index_path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            data = json.loads(stripped)
            if (
                int(data.get("schema_version", 0))
                != AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
            ):
                continue
            artifact_data = data.get("artifact")
            if isinstance(artifact_data, dict):
                rows.append(agent_artifact_from_dict(artifact_data))
    return rows


def _write_index_unlocked(index_path: Path, rows: list[AgentArtifact]) -> None:
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
                            "schema_version": AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
                            "artifact": agent_artifact_to_dict(row),
                        },
                        sort_keys=True,
                    )
                )
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, index_path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


@contextmanager
def _index_lock(index_path: Path, *, exclusive: bool) -> Iterator[None]:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = index_path.parent / _LOCK_NAME
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
