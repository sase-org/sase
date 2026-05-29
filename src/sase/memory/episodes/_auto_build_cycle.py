"""Top-level cycle orchestration for automatic episode builds."""

from __future__ import annotations

from collections.abc import Callable
import fcntl
from pathlib import Path
import time

from sase.memory.episodes._auto_build_locks import (
    release_episode_lock,
    try_acquire_episode_lock,
)
from sase.memory.episodes._auto_build_metrics import (
    append_metrics_unlocked,
    metrics_row,
)
from sase.memory.episodes._auto_build_runner import run_auto_build_locked
from sase.memory.episodes._auto_build_state import (
    failure_state,
    in_backoff,
    now_iso,
    read_build_state_details_unlocked,
    write_build_state_unlocked,
)
from sase.memory.episodes._auto_build_types import EpisodeAutoBuildReport
from sase.memory.episodes.index import (
    episode_index_lock_path,
    episode_index_path,
    project_episodes_dir,
)
from sase.memory.episodes.storage import EpisodeWriteResult

EpisodeWriter = Callable[..., EpisodeWriteResult]


def run_episode_auto_build_cycle(
    project: str,
    *,
    projects_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    limit: int | None,
    dry_run: bool = False,
    now_fn: Callable[[], str] | None = None,
    write_episode_unlocked: EpisodeWriter,
) -> EpisodeAutoBuildReport:
    """Run one checkpointed automatic episode build cycle."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be >= 1")
    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    index_path = episode_index_path(project, projects_root=projects_root)
    started_at = now_iso(now_fn)
    wall_start = time.perf_counter()
    held = try_acquire_episode_lock(episode_index_lock_path(index_path), fcntl.LOCK_EX)
    if held is None:
        return EpisodeAutoBuildReport(
            project=project,
            episodes_dir=str(episodes_dir.resolve(strict=False)),
            status="lock_busy",
            message="Episode index lock is held by another writer.",
            dry_run=dry_run,
            lock_acquired=False,
            lock_wait_seconds=0.0,
            checkpoint_before=None,
            checkpoint_after=None,
        )

    try:
        state_status, state, state_error = read_build_state_details_unlocked(
            episodes_dir,
            project,
        )
        if state is None:
            return EpisodeAutoBuildReport(
                project=project,
                episodes_dir=str(episodes_dir.resolve(strict=False)),
                status="state_corrupt",
                message="build_state.json is corrupt; run doctor to inspect or repair.",
                dry_run=dry_run,
                lock_acquired=True,
                lock_wait_seconds=held.wait_seconds,
                checkpoint_before=None,
                checkpoint_after=None,
                warnings=[state_error or "invalid build_state.json"],
                error=state_error,
            )
        if in_backoff(state, started_at):
            return EpisodeAutoBuildReport(
                project=project,
                episodes_dir=str(episodes_dir.resolve(strict=False)),
                status="backoff",
                message=f"Automatic builder is in backoff until {state.backoff_until}.",
                dry_run=dry_run,
                lock_acquired=True,
                lock_wait_seconds=held.wait_seconds,
                checkpoint_before=state.checkpoint_timestamp,
                checkpoint_after=state.checkpoint_timestamp,
            )

        try:
            return run_auto_build_locked(
                project,
                state=state,
                state_status=state_status,
                episodes_dir=episodes_dir,
                projects_root=projects_root,
                repo_root=repo_root,
                limit=limit,
                dry_run=dry_run,
                started_at=started_at,
                wall_start=wall_start,
                lock_wait_seconds=held.wait_seconds,
                now_fn=now_fn,
                write_episode_unlocked=write_episode_unlocked,
            )
        except Exception as exc:
            finished_at = now_iso(now_fn)
            failed_state = failure_state(
                state,
                started_at=started_at,
                finished_at=finished_at,
                error=str(exc),
            )
            if not dry_run:
                write_build_state_unlocked(episodes_dir, failed_state)
                metric = metrics_row(
                    project,
                    state=failed_state,
                    started_at=started_at,
                    finished_at=finished_at,
                    status="error",
                    dry_run=dry_run,
                    limit=limit,
                    checkpoint_before=state.checkpoint_timestamp,
                    seeds_scanned=0,
                    seeds_skipped=0,
                    components_planned=0,
                    components_built=0,
                    aliases_written=0,
                    changed_count=0,
                    unchanged_count=0,
                    importance_histogram={},
                    lock_wait_seconds=held.wait_seconds,
                    wall_start=wall_start,
                    error=str(exc),
                )
                metrics_path = append_metrics_unlocked(episodes_dir, metric)
            else:
                metric = None
                metrics_path = None
            return EpisodeAutoBuildReport(
                project=project,
                episodes_dir=str(episodes_dir.resolve(strict=False)),
                status="error",
                message=f"Automatic builder failed: {exc}",
                dry_run=dry_run,
                lock_acquired=True,
                lock_wait_seconds=held.wait_seconds,
                checkpoint_before=state.checkpoint_timestamp,
                checkpoint_after=state.checkpoint_timestamp,
                metrics_path=(
                    str(metrics_path.resolve(strict=False))
                    if metrics_path is not None
                    else None
                ),
                metrics=metric.to_json_dict() if metric is not None else None,
                error=str(exc),
            )
    finally:
        release_episode_lock(held)


__all__ = ["run_episode_auto_build_cycle"]
