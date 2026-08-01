"""Standalone task-bead orchestration for ``sase bead work``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sase.bead.cli_work_cleanup import (
    ForcedReuseCleanupError,
    prepare_bead_work_force_reuse,
    preview_bead_work_force_reuse,
    rollback_task_work_launch,
)
from sase.bead.cli_work_commit import (
    TaskLaunchCheckpointError,
    checkpoint_task_work_launch,
)
from sase.bead.cli_work_context import resolve_task_vcs_launch_context
from sase.bead.cli_work_launch import launch_bead_work_agents
from sase.bead.cli_work_plan import (
    confirm_cleanup,
    confirm_launch,
    print_task_work_summary,
    render_task_cleanup_preview,
)
from sase.bead.model import IssueType, Status

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.project import BeadProject


type TaskLaunchState = Literal[
    "already_running",
    "declined",
    "dry_run",
    "launched",
]


@dataclass(frozen=True)
class TaskWorkResult:
    """Outcome of one standalone task-bead work request."""

    task_id: str
    agent_name: str
    launch_state: TaskLaunchState
    workspace_num: int | None = None

    @property
    def launched(self) -> bool:
        return self.launch_state == "launched"


class TaskBeadWorkError(RuntimeError):
    """A recoverable standalone task-bead launch failure."""


def launch_task_bead_work(
    proj: BeadProject,
    task_id: str,
    *,
    dry_run: bool,
    yes: bool,
    no_push: bool,
    yes_to_all: bool = False,
    feedback: str | None = None,
    timer: LaunchTimingRecorder | None = None,
) -> TaskWorkResult:
    """Validate, checkpoint, and launch one deterministic task worker."""
    if timer is None:
        from sase.agent.launch_timing import LaunchTimingRecorder

        owned_timer = LaunchTimingRecorder(
            "bead_work",
            {"bead_id": task_id, "dry_run": dry_run},
            info_env_vars=("SASE_BEAD_WORK_TIMING",),
            durable=True,
        )
        with owned_timer:
            return launch_task_bead_work(
                proj,
                task_id,
                dry_run=dry_run,
                yes=yes,
                no_push=no_push,
                yes_to_all=yes_to_all,
                feedback=feedback,
                timer=owned_timer,
            )

    issue = proj.show(task_id)
    if issue.issue_type is not IssueType.TASK:
        raise TaskBeadWorkError(
            f"sase bead work task launches require a task bead "
            f"(got {issue.issue_type.value} for {task_id})"
        )
    if issue.status not in {Status.OPEN, Status.READY, Status.IN_PROGRESS}:
        raise TaskBeadWorkError(
            f"task {task_id} cannot be launched from status={issue.status.value}; "
            "expected open, ready, or recoverable in_progress"
        )

    if issue.status is Status.IN_PROGRESS and issue.assignee:
        from sase.agent.names import get_live_agent_name_subset

        live = get_live_agent_name_subset({issue.assignee})
        if issue.assignee in live:
            print(
                f"Task {task_id} is already assigned to live agent "
                f"{issue.assignee}; no new agent was launched."
            )
            return TaskWorkResult(
                task_id=task_id,
                agent_name=issue.assignee,
                launch_state="already_running",
            )

    from sase.bead.work import (
        render_task_prompt,
        task_model_directive_value,
        task_work_segment_env,
    )
    from sase.bead.xprompts import (
        BeadXPromptNotFoundError,
        resolve_work_task_xprompt,
    )

    with timer.stage("xprompt_lookup"):
        try:
            work_task_xprompt = resolve_work_task_xprompt()
        except (BeadXPromptNotFoundError, ValueError) as exc:
            raise TaskBeadWorkError(str(exc)) from exc
    with timer.stage("vcs_context"):
        try:
            vcs_context = resolve_task_vcs_launch_context()
        except ValueError as exc:
            raise TaskBeadWorkError(str(exc)) from exc
    with timer.stage("prompt_render"):
        try:
            query = render_task_prompt(
                task_id,
                model=issue.model,
                size=issue.size,
                work_task_xprompt=work_task_xprompt,
                vcs_context=vcs_context,
                feedback=feedback,
            )
        except ValueError as exc:
            raise TaskBeadWorkError(str(exc)) from exc

    model = task_model_directive_value(issue.model, size=issue.size)
    print_task_work_summary(task_id, issue.title, model=model)
    try:
        preview = preview_bead_work_force_reuse(
            query,
            expected_names={task_id},
        )
    except ForcedReuseCleanupError as exc:
        raise TaskBeadWorkError(str(exc)) from exc

    if dry_run:
        render_task_cleanup_preview(task_id, preview)
        print("\n--- Task prompt (dry run) ---")
        print(query)
        return TaskWorkResult(
            task_id=task_id,
            agent_name=task_id,
            launch_state="dry_run",
        )

    if preview.has_destructive_targets:
        render_task_cleanup_preview(task_id, preview)
        if not yes_to_all:
            cleanup_confirmation = confirm_cleanup()
            if cleanup_confirmation is None:
                raise TaskBeadWorkError(
                    "refusing destructive agent cleanup with non-interactive "
                    "stdin; re-run with --yes-to-all to proceed non-interactively"
                )
            if not cleanup_confirmation:
                print("Aborted.")
                return TaskWorkResult(
                    task_id=task_id,
                    agent_name=task_id,
                    launch_state="declined",
                )

    if not (yes or yes_to_all):
        launch_confirmation = confirm_launch()
        if launch_confirmation is None:
            raise TaskBeadWorkError(
                "refusing agent launch with non-interactive stdin; re-run with "
                "--yes (or --yes-to-all) to proceed non-interactively"
            )
        if not launch_confirmation:
            print("Aborted.")
            return TaskWorkResult(
                task_id=task_id,
                agent_name=task_id,
                launch_state="declined",
            )

    with timer.stage("force_reuse_cleanup"):
        try:
            query = prepare_bead_work_force_reuse(
                query,
                expected_names={task_id},
            )
        except ForcedReuseCleanupError as exc:
            raise TaskBeadWorkError(str(exc)) from exc

    prior_status = issue.status
    prior_assignee = issue.assignee
    try:
        with timer.stage("preclaim"):
            proj.update(
                task_id,
                status=Status.IN_PROGRESS.value,
                assignee=task_id,
            )
    except (KeyError, ValueError) as exc:
        raise TaskBeadWorkError(str(exc)) from exc

    try:
        with timer.stage("graph_publication"):
            checkpoint_task_work_launch(
                proj.beads_dir,
                task_id,
                no_push=no_push,
                timer=timer,
            )
    except TaskLaunchCheckpointError as exc:
        rollback_task_work_launch(
            proj,
            task_id,
            prior_status=prior_status,
            prior_assignee=prior_assignee,
            no_push=no_push,
        )
        raise TaskBeadWorkError(str(exc)) from exc
    except Exception as exc:
        rollback_task_work_launch(
            proj,
            task_id,
            prior_status=prior_status,
            prior_assignee=prior_assignee,
            no_push=no_push,
        )
        raise TaskBeadWorkError(
            f"task launch checkpoint failed before agent launch for {task_id}: {exc}"
        ) from exc

    try:
        with timer.stage("agent_launch"):
            results = launch_bead_work_agents(
                query,
                segment_extra_env=task_work_segment_env(task_id),
                expected_names={task_id},
                launch_context=vcs_context,
            )
    except Exception as exc:
        launched_results = list(getattr(exc, "results", []))
        launched_pids = [result.pid for result in launched_results]
        rollback_task_work_launch(
            proj,
            task_id,
            prior_status=prior_status,
            prior_assignee=prior_assignee,
            no_push=no_push,
            launched_pids=launched_pids,
            launched_results=launched_results,
        )
        raise TaskBeadWorkError(
            f"agent launch failed for task {task_id}: {exc}\n"
            "For broader diagnostics, run `sase doctor -v`."
        ) from exc

    if len(results) != 1:
        launched_pids = [result.pid for result in results]
        rollback_task_work_launch(
            proj,
            task_id,
            prior_status=prior_status,
            prior_assignee=prior_assignee,
            no_push=no_push,
            launched_pids=launched_pids,
            launched_results=results,
        )
        raise TaskBeadWorkError(
            f"agent launch failed for task {task_id}: expected exactly one task "
            f"agent, but launcher returned {len(results)} results"
        )

    workspace_num = results[0].workspace_num
    print(
        f"✓ Launched agent {task_id} for task {task_id} — {issue.title} "
        f"(workspace {workspace_num})"
    )
    return TaskWorkResult(
        task_id=task_id,
        agent_name=task_id,
        launch_state="launched",
        workspace_num=workspace_num,
    )


__all__ = [
    "TaskBeadWorkError",
    "TaskLaunchState",
    "TaskWorkResult",
    "launch_task_bead_work",
]
