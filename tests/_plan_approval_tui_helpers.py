"""Shared test helpers for TUI plan approval handling."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.task_actions import TrackedTaskCompletion
from sase.ace.tui.task_queue import TaskInfo
from sase.notifications import Notification
from tests.plan_validation_helpers import VALID_TALE_PLAN


def make_approval_app_and_notification(
    tmp_path: Path,
) -> tuple[MagicMock, Notification, Path, MagicMock]:
    """Create a mock app, notification, and response directory."""
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    (response_dir / "plan_request.json").write_text("{}")

    plan_file = tmp_path / "plan.md"
    plan_file.write_text(VALID_TALE_PLAN)

    notification = Notification(
        id="test-notif",
        timestamp="2026-03-31T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={"response_dir": str(response_dir)},
        files=[str(plan_file)],
    )

    mock_agent = MagicMock()
    mock_agent.identity = "test-agent-identity"

    app = MagicMock()
    app._agent_status_overrides = {}
    app._agent_pre_question_status = {}

    return app, notification, response_dir, mock_agent


def run_tracked_tasks_immediately(app: MagicMock) -> list[dict[str, Any]]:
    """Configure an app to execute submitted tracked tasks synchronously."""
    submitted: list[dict[str, Any]] = []

    def submit(
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Any,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> TaskInfo:
        del duplicate_message, reload_on_complete, notify_on_complete
        task_info = TaskInfo(
            task_id=f"task-{len(submitted)}",
            task_type=task_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=datetime.now(),
            display_name=display_name,
            dedup_key=dedup_key,
        )
        submitted.append(
            {
                "task_type": task_type,
                "cl_name": cl_name,
                "project_file": project_file,
                "display_name": display_name,
                "dedup_key": dedup_key,
                "task_callable": task_callable,
            }
        )
        result = task_callable()
        task_info.status = "success" if result.success else "error"
        task_info.message = result.message
        task_info.error = result.error
        if on_complete is not None:
            on_complete(
                TrackedTaskCompletion(
                    task_info=task_info,
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return task_info

    app._submit_tracked_task.side_effect = submit
    return submitted
