"""Best-effort lifecycle maintenance for the agent artifact index."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    delete_agent_artifact_index_row,
    replace_agent_artifact_index_dismissed_agents,
    upsert_agent_artifact_index_row,
)
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire

log = logging.getLogger(__name__)

AgentIdentityLike = tuple[Any, str, str | None]

_LIFECYCLE_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=True,
    include_raw_prompt_snippets=False,
)
_INDEX_ERRORS = (ImportError, AttributeError, OSError, RuntimeError, ValueError)


def _default_projects_root(sase_home: Path | str | None = None) -> Path:
    """Return the default projects root used by the artifact index."""
    root = Path(sase_home).expanduser() if sase_home is not None else Path.home() / ".sase"
    return root / "projects"


def _projects_root_for_artifact_dir(artifact_dir: Path | str) -> Path:
    """Resolve the projects root that contains *artifact_dir* when possible."""
    path = Path(artifact_dir).expanduser()
    for candidate in (path, *path.parents):
        if candidate.name == "projects":
            return candidate
    return _default_projects_root()


def sync_dismissed_agent_artifact_index(
    dismissed: Iterable[AgentIdentityLike],
    *,
    index_path: Path | str | None = None,
) -> bool:
    """Best-effort sync of dismissed identities into the SQLite artifact index."""
    index = Path(index_path).expanduser() if index_path is not None else default_agent_artifact_index_path()
    if not index.is_file():
        return False
    identities = [_identity_to_wire(identity) for identity in dismissed]
    try:
        replace_agent_artifact_index_dismissed_agents(index, identities)
    except _INDEX_ERRORS:
        log.debug("agent artifact index dismissed sync failed", exc_info=True)
        return False
    return True


def delete_agent_artifact_index_artifacts(
    artifact_dirs: Iterable[Path | str | None],
    *,
    index_path: Path | str | None = None,
) -> int:
    """Best-effort delete of artifact rows from the SQLite index."""
    index = Path(index_path).expanduser() if index_path is not None else default_agent_artifact_index_path()
    if not index.is_file():
        return 0

    deleted = 0
    for artifact_dir in artifact_dirs:
        if artifact_dir is None:
            continue
        try:
            update = delete_agent_artifact_index_row(index, Path(artifact_dir).expanduser())
        except _INDEX_ERRORS:
            log.debug(
                "agent artifact index row delete failed: %s",
                artifact_dir,
                exc_info=True,
            )
            continue
        deleted += update.rows_deleted
    return deleted


def upsert_agent_artifact_index_artifacts(
    artifact_dirs: Iterable[Path | str | None],
    *,
    index_path: Path | str | None = None,
) -> int:
    """Best-effort upsert of restored or changed artifact rows."""
    index = Path(index_path).expanduser() if index_path is not None else default_agent_artifact_index_path()
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


def _identity_to_wire(identity: AgentIdentityLike) -> AgentCleanupIdentityWire:
    agent_type, cl_name, raw_suffix = identity
    return AgentCleanupIdentityWire(
        agent_type=str(getattr(agent_type, "value", agent_type)),
        cl_name=str(cl_name),
        raw_suffix=None if raw_suffix is None else str(raw_suffix),
    )


__all__ = [
    "delete_agent_artifact_index_artifacts",
    "sync_dismissed_agent_artifact_index",
    "update_agent_artifact_index_for_marker_mutation",
    "upsert_agent_artifact_index_artifacts",
]
