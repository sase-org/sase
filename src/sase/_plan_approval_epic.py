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
    from sase.bead.epic_launch import EpicLaunchOrigin
    from sase.bead.epic_launch import EpicLaunchSubmission


def prepare_epic_launch(
    notification: PlanApprovalActionContext,
    plan_file: str | Path,
    *,
    mode: EpicLaunchMode,
    response_dir: Path,
    resolved_project: str | None = None,
    origin: EpicLaunchOrigin = "api",
) -> EpicLaunchSubmission | None:
    """Start the host-owned epic launch, or intentionally skip it."""
    # Host launches now log through a monitor or proc supervisor, so no
    # caller-owned response directory is needed; the parameter stays for
    # callers' sake.
    del response_dir
    if mode not in {"launch", "detached", "skip"}:
        raise PlanApprovalActionError(
            "invalid_request",
            "epic_launch_mode",
            f"unsupported epic launch mode: {mode}",
        )
    if mode == "skip":
        return None
    project = resolved_project or epic_launch_project(notification)
    primary_dir = _epic_launch_primary_checkout_or_none(project)
    if project is None or primary_dir is None:
        _raise_unclaimable_epic_launch(plan_file)

    plan_path = str(plan_file)
    try:
        from sase.bead.cli_work_from_plan import require_epic_launch_store_health

        require_epic_launch_store_health(primary_dir)
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
    from sase.bead.epic_launch import build_epic_launch_argv, start_epic_launch_monitor

    try:
        return start_epic_launch_monitor(
            plan_path,
            project=project,
            host_action_data=notification.host_action_data,
            artifacts_dir=resolve_plan_agent_artifacts_dir(
                notification.host_action_data
            ),
            cl_name=notification.host_action_data.get("agent_cl_name"),
            origin=origin,
        )
    except Exception as exc:
        resume = shlex.join(build_epic_launch_argv(plan_path))
        raise PlanApprovalActionError(
            "epic_launch_failed",
            plan_path,
            f"could not start the epic launch monitor: {exc}; resume with `{resume}`",
        ) from exc


def can_claim_epic_launch(
    notification: PlanApprovalActionContext,
    *,
    mode: EpicLaunchMode,
) -> bool:
    """Require that the host can durably claim an epic launch."""
    if mode not in {"launch", "detached", "skip"}:
        raise PlanApprovalActionError(
            "invalid_request",
            "epic_launch_mode",
            f"unsupported epic launch mode: {mode}",
        )
    if mode == "skip":
        return True
    project = epic_launch_project(notification)
    if project is None or _epic_launch_primary_checkout_or_none(project) is None:
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


def epic_launch_project(notification: PlanApprovalActionContext) -> str | None:
    project_dir = notification.host_action_data.get("project_dir")
    agent_project_file = notification.host_action_data.get("agent_project_file")
    if not project_dir and not agent_project_file:
        return None
    try:
        from sase.bead.epic_launch import resolve_epic_launch_project

        return resolve_epic_launch_project(
            project_dir,
            agent_project_file=agent_project_file,
        )
    except Exception:
        return None


def _epic_launch_primary_checkout_or_none(project: str | None) -> Path | None:
    """Read-only preflight: confirm *project*'s primary checkout exists.

    This never authorizes a mutation; it only fails the launch fast when the
    primary checkout used to resolve config, remotes, and project identity
    is missing. The actual launch runs in a leased checkout, never here.
    """
    if not project:
        return None
    from sase.running_field import get_workspace_directory

    primary = Path(get_workspace_directory(project, 1)).expanduser()
    return primary if primary.is_dir() else None
