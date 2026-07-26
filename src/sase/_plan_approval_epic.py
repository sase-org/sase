"""Host-owned epic launch behavior for plan approvals."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from sase._plan_approval_artifacts import resolve_plan_agent_artifacts_dir
from sase._plan_approval_protocol import (
    EpicLaunchMode,
    PlanApprovalActionContext,
    PlanApprovalActionError,
)

if TYPE_CHECKING:
    from sase.tasks.models import BackgroundTask


def prepare_epic_launch(
    notification: PlanApprovalActionContext,
    plan_file: str | Path,
    *,
    mode: EpicLaunchMode,
    response_dir: Path,
    resolved_cwd: Path | None = None,
) -> BackgroundTask | None:
    """Start the host-owned epic launch, or intentionally skip it."""
    # Detached launches now log through the task supervisor, so no caller-owned
    # response directory is needed; the parameter stays for callers' sake.
    del response_dir
    if mode not in {"detached", "skip"}:
        raise PlanApprovalActionError(
            "invalid_request",
            "epic_launch_mode",
            f"unsupported epic launch mode: {mode}",
        )
    if mode == "skip":
        return None
    cwd = resolved_cwd or epic_launch_cwd(notification)
    if cwd is None:
        _raise_unclaimable_epic_launch(plan_file)

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
    from sase.bead.epic_launch import (
        build_epic_launch_argv,
        submit_epic_launch_task,
    )

    try:
        return submit_epic_launch_task(
            plan_path,
            cwd=cwd,
            artifacts_dir=resolve_plan_agent_artifacts_dir(
                notification.host_action_data
            ),
            cl_name=notification.host_action_data.get("agent_cl_name"),
        )
    except Exception as exc:
        resume = shlex.join(build_epic_launch_argv(plan_path))
        raise PlanApprovalActionError(
            "epic_launch_failed",
            plan_path,
            f"could not submit the epic launch task: {exc}; resume with `{resume}`",
        ) from exc


def can_claim_epic_launch(
    notification: PlanApprovalActionContext,
    *,
    mode: EpicLaunchMode,
) -> bool:
    """Require that the host can durably claim an epic launch."""
    if mode not in {"detached", "skip"}:
        raise PlanApprovalActionError(
            "invalid_request",
            "epic_launch_mode",
            f"unsupported epic launch mode: {mode}",
        )
    if mode == "skip":
        return True
    if epic_launch_cwd(notification) is None:
        plan_file = notification.host_files[0] if notification.host_files else "plan"
        _raise_unclaimable_epic_launch(plan_file)
    return True


def _raise_unclaimable_epic_launch(plan_file: str | Path) -> NoReturn:
    from sase.bead.epic_launch import build_epic_launch_argv

    plan_path = str(plan_file)
    resume = shlex.join(build_epic_launch_argv(plan_path))
    raise PlanApprovalActionError(
        "epic_launch_failed",
        plan_path,
        "could not resolve the primary workspace for the approved epic; "
        f"resume with `{resume}`",
    )


def epic_launch_cwd(notification: PlanApprovalActionContext) -> Path | None:
    project_dir = notification.host_action_data.get("project_dir")
    agent_project_file = notification.host_action_data.get("agent_project_file")
    if not project_dir and not agent_project_file:
        return None
    try:
        from sase.bead.epic_launch import resolve_epic_launch_cwd

        return resolve_epic_launch_cwd(
            project_dir,
            agent_project_file=agent_project_file,
        )
    except Exception:
        return None
