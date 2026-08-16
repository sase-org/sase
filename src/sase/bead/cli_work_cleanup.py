"""Compatibility facade and launch rollback helpers for ``sase bead work``."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sase.bead.cli_work_cleanup_apply import (
    prepare_selected_bead_work_force_reuse as prepare_selected_bead_work_force_reuse,
)
from sase.bead.cli_work_cleanup_apply import (
    revalidate_bead_work_launch_selection as revalidate_bead_work_launch_selection,
)
from sase.bead.cli_work_cleanup_selection import (
    preview_bead_work_force_reuse as preview_bead_work_force_reuse,
)
from sase.bead.cli_work_cleanup_selection import (
    preview_bead_work_launch_selection as preview_bead_work_launch_selection,
)
from sase.bead.cli_work_cleanup_types import (
    BeadWorkLaunchSelection as _BeadWorkLaunchSelection,
)
from sase.bead.cli_work_cleanup_types import BeadWorkSlot as BeadWorkSlot
from sase.bead.cli_work_cleanup_types import CleanupAction as CleanupAction
from sase.bead.cli_work_cleanup_types import CleanupPreview as CleanupPreview
from sase.bead.cli_work_cleanup_types import CleanupTarget as CleanupTarget
from sase.bead.cli_work_name_cleanup import (
    ForcedReuseCleanupError as ForcedReuseCleanupError,
)

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult
    from sase.bead.model import Status
    from sase.bead.project import BeadProject, EpicPreclaimRollback


def _rollback_launched_agents(
    *,
    launched_results: list[AgentLaunchResult] | None,
    launched_pids: list[int] | None,
) -> None:
    if launched_results:
        from sase.agent.partial_launch import rollback_partial_launch_results

        rollback_partial_launch_results(launched_results)
        return

    if not launched_pids:
        return

    import signal

    for pid in launched_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            print(
                f"Warning: failed to terminate partially-launched pid {pid}: {exc}",
                file=sys.stderr,
            )


def rollback_work_launch(
    proj: BeadProject,
    epic_id: str,
    *,
    marked_ready_this_run: bool,
    rollback_preclaims: Sequence[EpicPreclaimRollback] = (),
    no_push: bool = False,
    launched_pids: list[int] | None = None,
    launched_results: list[AgentLaunchResult] | None = None,
) -> None:
    """Persist recoverable state after a failed epic-work agent launch.

    A zero-spawn failure restores every batch preclaim plus readiness when this
    launch set it. Once any runner has spawned, the preassigned state is
    retained and only the partial launch is terminated.
    """
    spawned_any = bool(launched_results or launched_pids)
    _rollback_launched_agents(
        launched_results=launched_results,
        launched_pids=launched_pids,
    )

    if spawned_any:
        print(
            "Terminated the partially launched agents; preserving "
            "is_ready_to_work and all epic work preclaims for recovery.",
            file=sys.stderr,
        )
        return

    if marked_ready_this_run:
        readiness_message = "restoring the epic's prior is_ready_to_work state"
    else:
        readiness_message = "preserving the epic's existing is_ready_to_work state"
    print(
        f"No agents were spawned; restoring {len(rollback_preclaims)} epic work "
        f"preclaim(s) and {readiness_message}.",
        file=sys.stderr,
    )

    from sase.bead.sync import (
        bead_store_write_lock,
        commit_failed_work_launch_recovery,
        push_bead_work_launch,
    )

    committed = False
    try:
        with bead_store_write_lock(proj.beads_dir) as already_locked:
            for prior in rollback_preclaims:
                try:
                    proj.update(
                        prior.bead_id,
                        status=prior.status.value,
                        assignee=prior.assignee,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"Warning: failed to restore preclaim on "
                        f"{prior.bead_id}: {exc}",
                        file=sys.stderr,
                    )
            if marked_ready_this_run:
                try:
                    proj.unmark_ready_to_work(epic_id)
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"Warning: failed to restore is_ready_to_work on "
                        f"{epic_id}: {exc}",
                        file=sys.stderr,
                    )
            committed = commit_failed_work_launch_recovery(
                proj.beads_dir,
                epic_id,
                already_locked=already_locked,
            )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Warning: failed to commit restored launch state for {epic_id}: {exc}",
            file=sys.stderr,
        )
        return

    if committed and not no_push:
        outcome = push_bead_work_launch(proj.beads_dir)
        if outcome.error is not None:
            print(
                f"Warning: failed to publish restored launch state for "
                f"{epic_id}: {outcome.error}",
                file=sys.stderr,
            )


def rollback_task_work_launch(
    proj: BeadProject,
    task_id: str,
    *,
    prior_status: Status,
    prior_assignee: str,
    no_push: bool = False,
    launched_pids: list[int] | None = None,
    launched_results: list[AgentLaunchResult] | None = None,
) -> None:
    """Persist recoverable state after a failed task-worker launch."""
    spawned_any = bool(launched_results or launched_pids)
    _rollback_launched_agents(
        launched_results=launched_results,
        launched_pids=launched_pids,
    )

    if spawned_any:
        print(
            "Terminated the partially launched task agent; preserving the "
            "in-progress task assignment for recovery.",
            file=sys.stderr,
        )
        return

    print(
        f"No agents were spawned; restoring task {task_id} to "
        f"status={prior_status.value} and its prior assignee.",
        file=sys.stderr,
    )
    from sase.bead.sync import (
        bead_store_write_lock,
        commit_failed_work_launch_recovery,
        push_bead_work_launch,
    )

    committed = False
    try:
        with bead_store_write_lock(proj.beads_dir) as already_locked:
            proj.update(
                task_id,
                status=prior_status.value,
                assignee=prior_assignee,
            )
            committed = commit_failed_work_launch_recovery(
                proj.beads_dir,
                task_id,
                already_locked=already_locked,
            )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Warning: failed to commit restored launch state for {task_id}: {exc}",
            file=sys.stderr,
        )
        return

    if committed and not no_push:
        outcome = push_bead_work_launch(proj.beads_dir)
        if outcome.error is not None:
            print(
                f"Warning: failed to publish restored launch state for "
                f"{task_id}: {outcome.error}",
                file=sys.stderr,
            )


__all__ = [
    "BeadWorkSlot",
    "CleanupAction",
    "CleanupPreview",
    "CleanupTarget",
    "ForcedReuseCleanupError",
    "prepare_selected_bead_work_force_reuse",
    "preview_bead_work_force_reuse",
    "preview_bead_work_launch_selection",
    "revalidate_bead_work_launch_selection",
    "rollback_task_work_launch",
    "rollback_work_launch",
]
