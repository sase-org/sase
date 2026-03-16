"""Convenience functions that construct and store notifications."""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sase.notifications.models import Notification
from sase.notifications.store import append_notification
from sase.sase_utils import EASTERN_TZ


def notify_workflow_complete(
    sender: str,
    cl_name: str | None,
    success: bool,
    notes: list[str],
    action: str | None = None,
    action_data: dict[str, str] | None = None,
    extra_files: list[str] | None = None,
) -> None:
    """Send a notification when a workflow finishes."""
    files = list(extra_files or [])
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(EASTERN_TZ).isoformat(),
        sender=sender,
        notes=notes,
        files=files,
        action=action,
        action_data=action_data or {},
    )
    append_notification(n)


def notify_sync_result(
    status: str,
    cl_name: str,
    workspace_dir: str,
    project_file: str,
) -> None:
    """Send a notification after a sync action completes."""
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(EASTERN_TZ).isoformat(),
        sender="sync",
        notes=[f"Sync {status} for {cl_name}"],
        files=[project_file],
        action="JumpToChangeSpec",
        action_data={"changespec_name": cl_name, "project_file": project_file},
    )
    append_notification(n)


def notify_axe_error_digest(
    errors: list[dict],
) -> None:
    """Send a digest notification summarising recent axe errors."""
    digest_dir = Path.home() / ".sase" / "axe" / "error_digests"
    digest_dir.mkdir(parents=True, exist_ok=True)
    digest_file = (
        digest_dir / f"digest_{datetime.now(EASTERN_TZ).strftime('%Y%m%d_%H%M%S')}.txt"
    )
    lines: list[str] = []
    for i, err in enumerate(errors, 1):
        lines.append(f"{'=' * 60}")
        lines.append(f"Error {i}/{len(errors)}")
        lines.append(f"  Time:       {err.get('timestamp', 'unknown')}")
        lines.append(f"  Lumberjack: {err.get('lumberjack', 'unknown')}")
        lines.append(f"  Job:        {err.get('job', 'unknown')}")
        lines.append(f"  Error:      {err.get('error', 'unknown')}")
        tb = err.get("traceback", "")
        if tb:
            lines.append("  Traceback:")
            for tb_line in tb.splitlines():
                lines.append(f"    {tb_line}")
        lines.append("")
    digest_file.write_text("\n".join(lines))

    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(EASTERN_TZ).isoformat(),
        sender="axe",
        notes=[f"{len(errors)} error(s) in the last hour"],
        files=[str(digest_file)],
        action=None,
        action_data={},
    )
    append_notification(n)


def notify_hitl_request(
    step_name: str,
    workflow_name: str,
    artifacts_dir: str,
) -> None:
    """Send a notification when a HITL prompt is waiting for user input."""
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(EASTERN_TZ).isoformat(),
        sender="hitl",
        notes=[f"HITL waiting: step '{step_name}' in {workflow_name}"],
        action="HITL",
        action_data={"artifacts_dir": artifacts_dir},
    )
    append_notification(n)


def notify_user_question(
    response_dir: str,
    session_id: str,
    notes: str,
    agent_cl_name: str | None = None,
    agent_project_file: str | None = None,
    agent_timestamp: str | None = None,
) -> None:
    """Send a notification when Claude Code asks a user question via hook."""
    action_data: dict[str, str] = {
        "response_dir": response_dir,
        "session_id": session_id,
    }
    if agent_cl_name:
        action_data["agent_cl_name"] = agent_cl_name
    if agent_project_file:
        action_data["agent_project_file"] = agent_project_file
    if agent_timestamp:
        action_data["agent_timestamp"] = agent_timestamp
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(EASTERN_TZ).isoformat(),
        sender="question",
        notes=[notes] if notes else ["Claude is asking a question"],
        files=[],
        action="UserQuestion",
        action_data=action_data,
    )
    append_notification(n)


def notify_plan_approval(
    plan_file: str,
    response_dir: str,
    session_id: str,
    project_dir: str | None = None,
    agent_cl_name: str | None = None,
    agent_project_file: str | None = None,
    agent_timestamp: str | None = None,
    epic_available: bool = False,
) -> None:
    """Send a notification when a Claude Code plan is ready for approval."""
    plan_name = plan_file.rsplit("/", 1)[-1] if "/" in plan_file else plan_file
    action_data: dict[str, str] = {
        "response_dir": response_dir,
        "session_id": session_id,
    }
    if project_dir:
        action_data["project_dir"] = project_dir
    if agent_cl_name:
        action_data["agent_cl_name"] = agent_cl_name
    if agent_project_file:
        action_data["agent_project_file"] = agent_project_file
    if agent_timestamp:
        action_data["agent_timestamp"] = agent_timestamp
    if epic_available:
        action_data["epic_available"] = "true"
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(EASTERN_TZ).isoformat(),
        sender="plan",
        notes=[f"Plan ready for review: {plan_name}"],
        files=[plan_file],
        action="PlanApproval",
        action_data=action_data,
    )
    append_notification(n)
