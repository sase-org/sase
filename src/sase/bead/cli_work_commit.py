"""Pre-spawn checkpoint helpers for ``sase bead work`` launches."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder


class EpicLaunchCheckpointError(RuntimeError):
    """A pre-spawn checkpoint or publication failure."""

    def __init__(
        self,
        message: str,
        *,
        checkpoint_created: bool,
        retry_requires_push: bool = False,
    ) -> None:
        super().__init__(message)
        self.checkpoint_created = checkpoint_created
        self.retry_requires_push = retry_requires_push


class TaskLaunchCheckpointError(RuntimeError):
    """A task worker's pre-spawn checkpoint or publication failure."""


def checkpoint_epic_work_launch(
    beads_dir: Path,
    epic_id: str,
    *,
    no_push: bool,
    timer: LaunchTimingRecorder,
) -> bool:
    """Commit and, when required, publish an epic launch before spawning.

    Returns whether a remote publication completed. A local checkpoint remains
    the safe retry point when publication fails after the commit.
    """
    from sase.bead.sync import (
        bead_state_is_clean,
        commit_epic_graph_checkpoint,
        push_bead_work_launch,
    )

    try:
        with timer.stage("commit"):
            commit_epic_graph_checkpoint(beads_dir, epic_id)
            if not bead_state_is_clean(beads_dir):
                raise RuntimeError("bead-state changes remain uncommitted")
    except Exception as exc:
        raise EpicLaunchCheckpointError(
            f"epic launch checkpoint failed before agent launch for {epic_id}: {exc}",
            checkpoint_created=False,
        ) from exc

    requires_remote = _requires_remote_publication(beads_dir)
    if no_push:
        if requires_remote:
            raise EpicLaunchCheckpointError(
                "--no-push cannot launch workers from this detached bead store; "
                "the launch checkpoint was committed locally and no agents were "
                "spawned. Retry without --no-push to publish it",
                checkpoint_created=True,
                retry_requires_push=True,
            )
        print(f"Committed epic launch checkpoint for {epic_id}.")
        return False

    with timer.stage("push", mode="sync"):
        outcome = push_bead_work_launch(beads_dir)
    if outcome.error is not None:
        raise EpicLaunchCheckpointError(
            f"epic launch checkpoint publication failed before agent launch "
            f"for {epic_id}: {outcome.error}",
            checkpoint_created=True,
            retry_requires_push=True,
        )
    if requires_remote and not outcome.pushed:
        raise EpicLaunchCheckpointError(
            f"epic launch checkpoint publication failed before agent launch "
            f"for {epic_id}: the detached bead store has no push remote",
            checkpoint_created=True,
            retry_requires_push=True,
        )

    suffix = " Pushed to remote." if outcome.pushed else ""
    print(f"Committed epic launch checkpoint for {epic_id}.{suffix}")
    return outcome.pushed


def checkpoint_task_work_launch(
    beads_dir: Path,
    task_id: str,
    *,
    no_push: bool,
    timer: LaunchTimingRecorder,
) -> bool:
    """Commit and, when required, publish one task assignment before spawn."""
    from sase.bead.sync import (
        bead_state_is_clean,
        commit_task_work_launch,
        push_bead_work_launch,
    )

    try:
        with timer.stage("commit"):
            commit_task_work_launch(beads_dir, task_id)
            if not bead_state_is_clean(beads_dir):
                raise RuntimeError("bead-state changes remain uncommitted")
    except Exception as exc:
        raise TaskLaunchCheckpointError(
            f"task launch checkpoint failed before agent launch for {task_id}: {exc}"
        ) from exc

    requires_remote = _requires_remote_publication(beads_dir)
    if no_push:
        if requires_remote:
            raise TaskLaunchCheckpointError(
                "--no-push cannot launch a task worker from this detached bead "
                "store; the launch checkpoint was committed locally and no "
                "agent was spawned"
            )
        print(f"Committed task launch checkpoint for {task_id}.")
        return False

    with timer.stage("push", mode="sync"):
        outcome = push_bead_work_launch(beads_dir)
    if outcome.error is not None:
        raise TaskLaunchCheckpointError(
            f"task launch checkpoint publication failed before agent launch "
            f"for {task_id}: {outcome.error}"
        )
    if requires_remote and not outcome.pushed:
        raise TaskLaunchCheckpointError(
            f"task launch checkpoint publication failed before agent launch "
            f"for {task_id}: the detached bead store has no push remote"
        )

    suffix = " Pushed to remote." if outcome.pushed else ""
    print(f"Committed task launch checkpoint for {task_id}.{suffix}")
    return outcome.pushed


def _requires_remote_publication(beads_dir: Path) -> bool:
    """Return whether detached workers need a remote bead-store revision."""
    from sase.bead.cli_location import resolve_beads_location

    location = resolve_beads_location(beads_dir, require_existing=True)
    if location is None or location.is_in_tree:
        return False
    if location.expected_remote_url:
        return True
    store = location.store
    if store is None:
        return False
    if store.beads_dir is not None and store.beads_remote_url:
        return True
    return bool(store.remote_url)


__all__ = [
    "EpicLaunchCheckpointError",
    "TaskLaunchCheckpointError",
    "checkpoint_epic_work_launch",
    "checkpoint_task_work_launch",
]
