"""Local pool storage, manifest append, and budget GC for prompt artifacts.

Split out of :mod:`sase.core.prompt_artifact_staging` to keep each module
under the 500-line cap. Staging and capture call these helpers; shared
types live in :mod:`sase.core._prompt_artifact_staging_shared`. The public
import path remains :mod:`sase.core.prompt_artifact_staging`.
"""

from __future__ import annotations

from collections import defaultdict
import fcntl
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import cast

from sase.config import get_artifact_capture_pool_max_bytes
from sase.core._prompt_artifact_staging_shared import (
    PROMPT_ARTIFACT_MANIFEST_LOCK_NAME,
    PROMPT_ARTIFACT_MANIFEST_NAME,
    PROMPT_ARTIFACT_POOL_DIR,
    PromptArtifactRecord,
)
from sase.core.artifact_file_helpers import hash_file
from sase.core.rust import require_rust_binding
from sase.memory.locks import locked_file


log = logging.getLogger(__name__)


def prune_prompt_artifact_pool(workspace_root: Path | str) -> int:
    """Remove published terminal-run pool files until the budget is met.

    A pooled file is eligible only when every manifest row that names it
    belongs to a terminal agent run whose commit checkpoint records successful
    prompt-archive publication. Manifest provenance is intentionally retained.
    """

    workspace = Path(workspace_root).expanduser().resolve(strict=False)
    staging_root = workspace / ".sase" / "artifacts"
    manifest_path = staging_root / PROMPT_ARTIFACT_MANIFEST_NAME
    lock_path = staging_root / PROMPT_ARTIFACT_MANIFEST_LOCK_NAME
    budget = get_artifact_capture_pool_max_bytes()
    removed = 0
    with locked_file(lock_path, fcntl.LOCK_EX):
        pool_files = _pool_files(staging_root)
        total_size = sum(size for _path, size in pool_files)
        if total_size <= budget or not manifest_path.is_file():
            return 0
        records = _parse_manifest(manifest_path.read_bytes())
        pending_revisions = _active_publication_revisions()
        rows_by_pool: dict[str, list[PromptArtifactRecord]] = defaultdict(list)
        for record in records:
            pool_relpath = record.get("pool_relpath")
            if isinstance(pool_relpath, str) and pool_relpath:
                rows_by_pool[pool_relpath].append(record)

        candidates: list[tuple[float, Path, int]] = []
        for path, size in pool_files:
            relpath = path.relative_to(staging_root).as_posix()
            rows = rows_by_pool.get(relpath, [])
            if (
                rows
                and pending_revisions is not None
                and all(
                    _run_is_terminal_and_published(row, pending_revisions)
                    for row in rows
                )
            ):
                candidates.append((path.stat().st_mtime, path, size))
        for _mtime, path, size in sorted(candidates):
            if total_size <= budget:
                break
            path.unlink(missing_ok=True)
            total_size -= size
            removed += 1
    return removed


def append_manifest_record(
    manifest_path: Path,
    lock_path: Path,
    record: PromptArtifactRecord,
) -> None:
    """Append one manifest row under the workspace staging lock."""

    with locked_file(lock_path, fcntl.LOCK_EX):
        _append_manifest_record_unlocked(manifest_path, record)


def store_and_append_record(
    *,
    source: Path,
    expected_sha256: str,
    pool_path: Path,
    manifest_path: Path,
    lock_path: Path,
    record: PromptArtifactRecord,
) -> bool:
    """Copy *source* into the pool (if needed) and append its manifest row."""

    with locked_file(lock_path, fcntl.LOCK_EX):
        created = _store_pool_file(source, pool_path, expected_sha256)
        _append_manifest_record_unlocked(manifest_path, record)
    return created


def store_captured_tmp_and_append_record(
    *,
    tmp_path: Path,
    expected_sha256: str,
    pool_path: Path,
    manifest_path: Path,
    lock_path: Path,
    record: PromptArtifactRecord,
) -> bool:
    """Promote a captured temp file into the pool and append its manifest row."""

    with locked_file(lock_path, fcntl.LOCK_EX):
        created = _store_captured_tmp(tmp_path, pool_path, expected_sha256)
        _append_manifest_record_unlocked(manifest_path, record)
    return created


def pool_exceeds_budget(staging_root: Path) -> bool:
    """Return True when the local pool is already over the configured cap."""

    budget = get_artifact_capture_pool_max_bytes()
    total = 0
    for _path, size in _pool_files(staging_root):
        total += size
        if total > budget:
            return True
    return False


def _append_manifest_record_unlocked(
    manifest_path: Path,
    record: PromptArtifactRecord,
) -> None:
    render = require_rust_binding("prompt_artifact_manifest_render_record")
    line = str(render(dict(record)))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as stream:
        stream.write(line)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _store_captured_tmp(
    tmp_path: Path,
    target: Path,
    expected_sha256: str,
) -> bool:
    if target.exists():
        if hash_file(target) != expected_sha256:
            raise RuntimeError(f"prompt artifact digest collision at {target}")
        return False
    if hash_file(tmp_path) != expected_sha256:
        raise RuntimeError("captured prompt artifact digest mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp_path, target)
    return True


def _store_pool_file(source: Path, target: Path, expected_sha256: str) -> bool:
    if target.exists():
        if hash_file(target) != expected_sha256:
            raise RuntimeError(f"prompt artifact digest collision at {target}")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    tmp_path = Path(tmp_name)
    try:
        shutil.copy2(source, tmp_path)
        if hash_file(tmp_path) != expected_sha256:
            raise RuntimeError(f"prompt artifact changed while staging: {source}")
        os.replace(tmp_path, target)
    finally:
        tmp_path.unlink(missing_ok=True)
    return True


def _pool_files(staging_root: Path) -> list[tuple[Path, int]]:
    pool_dir = staging_root / PROMPT_ARTIFACT_POOL_DIR
    try:
        return [
            (path, path.stat().st_size) for path in pool_dir.iterdir() if path.is_file()
        ]
    except OSError:
        return []


def _parse_manifest(data: bytes) -> list[PromptArtifactRecord]:
    parse = require_rust_binding("prompt_artifact_manifest_parse")
    return cast(list[PromptArtifactRecord], parse(data))


def _active_publication_revisions() -> frozenset[str] | None:
    """Return revisions with a queued or quarantined request, failing closed."""

    from sase.agents_sync.publication_outbox import (
        AGENT_PUBLICATION_OUTBOX_FILENAME,
        snapshot_agent_publications_from_path,
    )
    from sase.core.paths import sase_projects_dir

    pending: set[str] = set()
    try:
        projects_root = sase_projects_dir()
        for path in projects_root.glob(f"*/{AGENT_PUBLICATION_OUTBOX_FILENAME}"):
            for item in snapshot_agent_publications_from_path(path, path.parent.name):
                if not item.terminal:
                    pending.add(item.primary_revision)
    except Exception:
        log.debug(
            "Could not inspect agent-publication outboxes for pool GC", exc_info=True
        )
        return None
    return frozenset(pending)


def _run_is_terminal_and_published(
    record: PromptArtifactRecord,
    pending_revisions: frozenset[str],
) -> bool:
    raw_dir = record.get("agent_artifacts_dir")
    if not isinstance(raw_dir, str) or not raw_dir:
        return False
    artifacts_dir = Path(raw_dir).expanduser()
    if not (artifacts_dir / "done.json").is_file():
        return False
    try:
        checkpoint = json.loads(
            (artifacts_dir / "commit_state.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return False
    completed = (
        checkpoint.get("completed_steps") if isinstance(checkpoint, dict) else None
    )
    if not isinstance(completed, list) or not any(
        step in completed
        for step in (
            "publish_prompt_archive",
            "publish_agent_hood",
            "enqueue_agent_publication",
        )
    ):
        return False
    revision = checkpoint.get("primary_revision") or checkpoint.get("commit_sha")
    return (
        isinstance(revision, str)
        and bool(revision)
        and revision not in pending_revisions
    )


__all__ = [
    "append_manifest_record",
    "pool_exceeds_budget",
    "prune_prompt_artifact_pool",
    "store_and_append_record",
    "store_captured_tmp_and_append_record",
]
