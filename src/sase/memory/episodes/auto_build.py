"""Public facade for checkpointed automatic episode batch building."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.memory.episodes._auto_build_cycle import run_episode_auto_build_cycle
from sase.memory.episodes._auto_build_doctor import build_episode_auto_doctor_report
from sase.memory.episodes._auto_build_status import read_episode_auto_build_status
from sase.memory.episodes._auto_build_types import (
    AUTO_BUILD_STATE_SCHEMA_VERSION,
    BUILD_STATE_FILE_NAME,
    BUILD_STATE_PREV_FILE_NAME,
    DEFAULT_AUTO_BUILD_LIMIT,
    EpisodeAutoBuildReport,
    EpisodeAutoBuildStatus,
    EpisodeDoctorReport,
)
from sase.memory.episodes.storage import write_project_episode_unlocked


def run_episode_auto_build(
    project: str,
    *,
    projects_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    limit: int | None = DEFAULT_AUTO_BUILD_LIMIT,
    dry_run: bool = False,
    now_fn: Callable[[], str] | None = None,
) -> EpisodeAutoBuildReport:
    """Run one checkpointed automatic episode build cycle."""

    return run_episode_auto_build_cycle(
        project=project,
        projects_root=projects_root,
        repo_root=repo_root,
        limit=limit,
        dry_run=dry_run,
        now_fn=now_fn,
        write_episode_unlocked=write_project_episode_unlocked,
    )


__all__ = [
    "AUTO_BUILD_STATE_SCHEMA_VERSION",
    "BUILD_STATE_FILE_NAME",
    "BUILD_STATE_PREV_FILE_NAME",
    "DEFAULT_AUTO_BUILD_LIMIT",
    "EpisodeAutoBuildReport",
    "EpisodeAutoBuildStatus",
    "EpisodeDoctorReport",
    "build_episode_auto_doctor_report",
    "read_episode_auto_build_status",
    "run_episode_auto_build",
]
