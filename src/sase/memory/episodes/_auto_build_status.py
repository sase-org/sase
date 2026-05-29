"""Status readers for the automatic episode builder."""

from __future__ import annotations

from pathlib import Path

from sase.memory.episodes._auto_build_locks import lock_available
from sase.memory.episodes._auto_build_metrics import read_latest_metrics
from sase.memory.episodes._auto_build_state import read_build_state_details
from sase.memory.episodes._auto_build_types import EpisodeAutoBuildStatus
from sase.memory.episodes.index import (
    episode_index_lock_path,
    episode_index_path,
    project_episodes_dir,
    read_episode_index,
)
from sase.memory.episodes.inventory import canonical_index_rows


def read_episode_auto_build_status(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> EpisodeAutoBuildStatus:
    """Read automatic builder state and latest metrics for a project."""

    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    index_path = episode_index_path(project, projects_root=projects_root)
    state_status, state, state_error = read_build_state_details(episodes_dir, project)
    latest_metrics = read_latest_metrics(episodes_dir)
    return EpisodeAutoBuildStatus(
        project=project,
        episodes_dir=str(episodes_dir.resolve(strict=False)),
        index_path=str(index_path.resolve(strict=False)),
        lock_available=lock_available(episode_index_lock_path(index_path)),
        state_status=state_status,
        state_error=state_error,
        state=state.to_json_dict() if state is not None else None,
        episode_count=len(canonical_index_rows(project, projects_root)),
        index_row_count=len(read_episode_index(project, projects_root=projects_root)),
        latest_metrics=latest_metrics,
    )


__all__ = ["read_episode_auto_build_status"]
