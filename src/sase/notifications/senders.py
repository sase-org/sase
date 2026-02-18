"""Convenience functions that construct and store notifications."""

from datetime import datetime
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
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(EASTERN_TZ).isoformat(),
        sender="axe",
        notes=[f"{len(errors)} error(s) in the last hour"],
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
