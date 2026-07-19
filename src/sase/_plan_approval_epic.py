"""Host-owned epic launch behavior for plan approvals."""

from __future__ import annotations

import shlex
from pathlib import Path

from sase._plan_approval_artifacts import resolve_plan_agent_artifacts_dir
from sase._plan_approval_protocol import (
    EpicLaunchMode,
    PlanApprovalActionContext,
    PlanApprovalActionError,
)


def prepare_epic_launch(
    notification: PlanApprovalActionContext,
    plan_file: str | Path,
    *,
    mode: EpicLaunchMode,
    response_dir: Path,
    resolved_cwd: Path | None = None,
) -> bool:
    """Start the host-owned epic launch and report whether the host claimed it."""
    if mode not in {"detached", "foreground", "skip"}:
        raise PlanApprovalActionError(
            "invalid_request",
            "epic_launch_mode",
            f"unsupported epic launch mode: {mode}",
        )
    if mode == "skip":
        return True
    cwd = resolved_cwd or epic_launch_cwd(notification)
    if cwd is None:
        return False

    plan_path = str(plan_file)
    try:
        from sase.bead.cli_work_from_plan import require_epic_launch_store_health

        require_epic_launch_store_health(cwd)
    except Exception as exc:
        from sase.sdd._repository_transaction import SddRepositoryHealthError
        from sase.sdd._store_types import SddMaterializationError

        if not isinstance(exc, (SddMaterializationError, SddRepositoryHealthError)):
            raise
        from sase.bead.epic_launch import build_epic_launch_argv

        resume = shlex.join(build_epic_launch_argv(plan_path))
        raise PlanApprovalActionError(
            "epic_launch_failed",
            plan_path,
            f"approved epic plans store is unusable: {exc}; resume with `{resume}`",
        ) from exc
    if mode == "detached":
        try:
            from sase.bead.epic_launch import spawn_detached_epic_launch

            artifacts_dir = resolve_plan_agent_artifacts_dir(
                notification.host_action_data
            )
            log_root = Path(artifacts_dir) if artifacts_dir else response_dir
            spawn_detached_epic_launch(
                plan_path,
                cwd=cwd,
                log_path=log_root / "epic_launch.log",
                artifacts_dir=artifacts_dir,
                cl_name=notification.host_action_data.get("agent_cl_name"),
            )
            return True
        except Exception:
            return False

    try:
        from sase.bead.epic_launch import run_epic_launch_foreground

        completed = run_epic_launch_foreground(plan_path, cwd=cwd)
    except OSError as exc:
        raise PlanApprovalActionError(
            "epic_launch_failed", plan_path, f"could not start epic launch: {exc}"
        ) from exc
    if completed.returncode != 0:
        from sase.bead.epic_launch import build_epic_launch_argv

        resume = shlex.join(build_epic_launch_argv(plan_path))
        raise PlanApprovalActionError(
            "epic_launch_failed",
            plan_path,
            f"epic launch failed with exit code {completed.returncode}; resume with `{resume}`",
        )
    return True


def can_claim_epic_launch(
    notification: PlanApprovalActionContext,
    *,
    mode: EpicLaunchMode,
) -> bool:
    """Return whether the host can durably claim an epic launch."""
    if mode not in {"detached", "foreground", "skip"}:
        raise PlanApprovalActionError(
            "invalid_request",
            "epic_launch_mode",
            f"unsupported epic launch mode: {mode}",
        )
    return mode == "skip" or epic_launch_cwd(notification) is not None


def epic_launch_cwd(notification: PlanApprovalActionContext) -> Path | None:
    project_dir = notification.host_action_data.get("project_dir")
    if not project_dir:
        return None
    try:
        from sase.bead.epic_launch import resolve_epic_launch_cwd

        return resolve_epic_launch_cwd(
            project_dir,
            agent_project_file=notification.host_action_data.get("agent_project_file"),
        )
    except Exception:
        return None
