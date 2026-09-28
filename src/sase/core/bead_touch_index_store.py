"""Index-path resolution and refresh for the agent/bead touch index.

The reduction itself lives in ``sase-core`` (``bead/touch_index.rs``). This
module owns index-path resolution from :func:`sase_projects_dir`, the thin
refresh binding wrapper, the best-effort refresh entry point for the three
off-hot-path refresh sites (post-mutation, post-sync, lumberjack tick), and
the stat-only staleness report. Public names are re-exported through
:mod:`sase.core.bead_touch_index_facade`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.bead_touch_index_models import (
    TOUCH_INDEX_FILENAME,
    BeadTouchIndexStatus,
    BeadTouchRefresh,
)
from sase.core.paths import sase_projects_dir
from sase.core.rust import require_rust_binding

_logger = logging.getLogger(__name__)


def resolve_touch_index_project(
    *,
    project: str | None = None,
    cwd: Path | None = None,
    beads_dir: Path | None = None,
) -> str | None:
    """Return the projects-dir key owning the touch index, if resolvable.

    An explicit *project* wins (after alias resolution), mirroring
    :func:`sase.artifact_read_log.artifact_read_log_path`. Otherwise the
    project is inferred from *cwd* via the checkout marker / git / workspace
    chain, or from *beads_dir* via the workspace scan; anything unresolvable
    is ``None`` so refresh sites can skip quietly instead of guessing.
    """
    if project:
        try:
            from sase.project_aliases import resolve_project_alias_ref

            return resolve_project_alias_ref(project)
        except Exception:
            return project
    if cwd is not None:
        try:
            from sase.main.init_memory.config import project_memory_name
            from sase.project_aliases import resolve_project_alias_ref

            return resolve_project_alias_ref(project_memory_name(cwd.expanduser()))
        except Exception:
            return None
    if beads_dir is not None:
        try:
            from sase.bead.project_name import infer_project_name_from_cwd

            return infer_project_name_from_cwd(str(beads_dir.expanduser()))
        except Exception:
            return None
    return None


def touch_index_path(project: str | None = None, *, cwd: Path | None = None) -> Path:
    """Return ``~/.sase/projects/<key>/agent_bead_touches.json``."""
    from sase.project_aliases import resolve_project_alias_ref

    if project is not None:
        project_name = resolve_project_alias_ref(project)
    else:
        from sase.main.init_memory.config import project_memory_name

        project_name = resolve_project_alias_ref(
            project_memory_name((cwd or Path.cwd()).expanduser())
        )
    return sase_projects_dir() / project_name / TOUCH_INDEX_FILENAME


def _refresh_touch_index(
    beads_dir: Path | str, index_path: Path | str
) -> BeadTouchRefresh:
    """Bring the index at *index_path* up to date with *beads_dir*.

    Incremental and idempotent: unchanged streams keep their cached rows and
    the file is left untouched when nothing changed. Raises on genuine
    failures; refresh sites that must never break use
    :func:`refresh_touch_index_best_effort` instead.
    """
    binding = require_rust_binding("bead_touch_index_refresh")
    payload: Mapping[str, Any] = binding(str(beads_dir), str(index_path))
    return BeadTouchRefresh(
        schema_version=int(payload.get("schema_version", 0)),
        generation=str(payload.get("generation", "")),
        full_rebuild=bool(payload.get("full_rebuild", False)),
        wrote=bool(payload.get("wrote", False)),
        stream_count=int(payload.get("stream_count", 0)),
        reduced_streams=tuple(
            str(name) for name in payload.get("reduced_streams") or ()
        ),
        reused_streams=int(payload.get("reused_streams", 0)),
        removed_streams=tuple(
            str(name) for name in payload.get("removed_streams") or ()
        ),
        touch_count=int(payload.get("touch_count", 0)),
    )


def refresh_touch_index_best_effort(
    beads_dir: Path | str,
    *,
    project: str | None = None,
    cwd: Path | None = None,
    index_path: Path | str | None = None,
) -> BeadTouchRefresh | None:
    """Refresh the touch index, logging and swallowing every failure.

    Resolves *index_path* from *project*/*cwd* when not given; an
    unresolvable project is a quiet skip, never an error. Callers that only
    hold a store path resolve the project first with
    :func:`resolve_touch_index_project`. Returns the refresh outcome, or
    ``None`` when there was nothing to do or the refresh failed. A failed
    refresh never breaks a bead mutation, a sync, or a job tick; the next
    refresh site converges the store instead.
    """
    try:
        if index_path is not None:
            resolved_index = Path(index_path)
        else:
            resolved_project = resolve_touch_index_project(project=project, cwd=cwd)
            if not resolved_project:
                _logger.debug(
                    "Skipping bead touch-index refresh: no project for %s",
                    beads_dir,
                )
                return None
            resolved_index = (
                sase_projects_dir() / resolved_project / TOUCH_INDEX_FILENAME
            )
        return _refresh_touch_index(beads_dir, resolved_index)
    except Exception as exc:
        _logger.warning("Skipping bead touch-index refresh for %s: %s", beads_dir, exc)
        return None


def touch_index_status(
    beads_dir: Path | str, index_path: Path | str
) -> BeadTouchIndexStatus:
    """Classify the index against the live streams without reducing anything.

    Stat-only and lock-free: compares each stream file's ``(mtime_ns, size)``
    with the signature the index recorded. ``state`` is one of ``missing``,
    ``unreadable``, ``schema_mismatch``, ``stale``, or ``fresh``.
    """
    binding = require_rust_binding("bead_touch_index_status")
    payload: Mapping[str, Any] = binding(str(beads_dir), str(index_path))
    index_schema = payload.get("index_schema_version")
    return BeadTouchIndexStatus(
        schema_version=int(payload.get("schema_version", 0)),
        state=str(payload.get("state", "missing")),
        index_schema_version=(None if index_schema is None else int(index_schema)),
        generation=str(payload.get("generation", "")),
        indexed_streams=int(payload.get("indexed_streams", 0)),
        current_streams=int(payload.get("current_streams", 0)),
        changed_streams=tuple(
            str(name) for name in payload.get("changed_streams") or ()
        ),
        vanished_streams=tuple(
            str(name) for name in payload.get("vanished_streams") or ()
        ),
    )


__all__ = [
    "refresh_touch_index_best_effort",
    "resolve_touch_index_project",
    "touch_index_path",
    "touch_index_status",
]
