"""Best-effort row mutations for the persistent agent artifact index."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from sase.core.agent_artifact_index_lifecycle_common import (
    _INDEX_ERRORS,
    _LIFECYCLE_SCAN_OPTIONS,
    default_agent_artifact_projects_root,
)
from sase.core.agent_artifact_index_lock import agent_artifact_index_operation_lock
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    delete_agent_artifact_index_row,
    delete_agent_artifact_index_row_bounded,
    upsert_agent_artifact_index_row,
)

log = logging.getLogger(__name__)


def _projects_root_for_artifact_dir(artifact_dir: Path | str) -> Path:
    """Resolve the projects root that contains *artifact_dir* when possible."""
    path = Path(artifact_dir).expanduser()
    for candidate in (path, *path.parents):
        if candidate.name == "projects":
            return candidate
    return default_agent_artifact_projects_root()


def delete_agent_artifact_index_artifacts(
    artifact_dirs: Iterable[Path | str | None],
    *,
    index_path: Path | str | None = None,
) -> int:
    """Best-effort delete of artifact rows from the SQLite index."""
    with agent_artifact_index_operation_lock():
        index = (
            Path(index_path).expanduser()
            if index_path is not None
            else default_agent_artifact_index_path()
        )
        if not index.is_file():
            return 0

        deleted = 0
        for artifact_dir in artifact_dirs:
            if artifact_dir is None:
                continue
            try:
                update = delete_agent_artifact_index_row(
                    index, Path(artifact_dir).expanduser()
                )
            except _INDEX_ERRORS:
                log.debug(
                    "agent artifact index row delete failed: %s",
                    artifact_dir,
                    exc_info=True,
                )
                continue
            deleted += update.rows_deleted
        return deleted


def delete_agent_artifact_index_artifacts_bounded(
    artifact_dirs: Iterable[Path | str | None],
    *,
    index_path: Path | str | None = None,
    timeout_seconds: float,
) -> bool:
    """Best-effort delete that reports contention instead of waiting.

    Returns ``True`` only when every requested row was handled (including an
    already-absent index). A process-lock miss, SQLite busy timeout, or stale
    binding returns ``False`` so self-healing callers retry on their next pass.
    """
    index = (
        Path(index_path).expanduser()
        if index_path is not None
        else default_agent_artifact_index_path()
    )
    if not index.is_file():
        return True

    for artifact_dir in artifact_dirs:
        if artifact_dir is None:
            continue
        try:
            update = delete_agent_artifact_index_row_bounded(
                index,
                Path(artifact_dir).expanduser(),
                lock_timeout_seconds=timeout_seconds,
                busy_timeout_seconds=timeout_seconds,
            )
        except _INDEX_ERRORS:
            log.debug(
                "bounded agent artifact index row delete deferred: %s",
                artifact_dir,
                exc_info=True,
            )
            return False
        if update is None:
            return False
    return True


def upsert_agent_artifact_index_artifacts(
    artifact_dirs: Iterable[Path | str | None],
    *,
    index_path: Path | str | None = None,
) -> int:
    """Best-effort upsert of restored or changed artifact rows."""
    with agent_artifact_index_operation_lock():
        index = (
            Path(index_path).expanduser()
            if index_path is not None
            else default_agent_artifact_index_path()
        )
        indexed = 0
        seen: set[Path] = set()
        for artifact_dir in artifact_dirs:
            if artifact_dir is None:
                continue
            artifact_path = Path(artifact_dir).expanduser()
            if artifact_path in seen or not artifact_path.is_dir():
                continue
            seen.add(artifact_path)
            try:
                update = upsert_agent_artifact_index_row(
                    index,
                    _projects_root_for_artifact_dir(artifact_path),
                    artifact_path,
                    _LIFECYCLE_SCAN_OPTIONS,
                )
            except _INDEX_ERRORS:
                log.debug(
                    "agent artifact index row upsert failed: %s",
                    artifact_path,
                    exc_info=True,
                )
                continue
            indexed += update.rows_indexed
        return indexed


def update_agent_artifact_index_for_marker_mutation(
    artifact_dir: Path | str | None,
    *,
    index_path: Path | str | None = None,
) -> bool:
    """Best-effort index refresh after an agent marker file changes."""
    return (
        upsert_agent_artifact_index_artifacts([artifact_dir], index_path=index_path) > 0
    )
