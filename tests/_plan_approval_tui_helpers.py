"""Shared test helpers for TUI plan approval handling."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.proc_observer import ObservedProc as ProcInfo
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


def run_tracked_procs_immediately(app: MagicMock) -> list[dict[str, Any]]:
    """Configure an app to execute submitted tracked tasks synchronously."""
    submitted: list[dict[str, Any]] = []

    def submit(
        proc_type: str,
        proc_callable: Any,
        *,
        display_name: str | None = None,
        cl_name: str = "",
        project_file: str = "",
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        exclusive_scopes: Any = (),
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> ProcInfo:
        del duplicate_message, exclusive_scopes, reload_on_complete, notify_on_complete
        proc_info = ProcInfo(
            proc_id=f"task-{len(submitted)}",
            proc_type=proc_type,
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
                "proc_type": proc_type,
                "cl_name": cl_name,
                "project_file": project_file,
                "display_name": display_name,
                "dedup_key": dedup_key,
                "proc_callable": proc_callable,
            }
        )
        result = proc_callable()
        proc_info.status = "success" if result.success else "error"
        proc_info.message = result.message
        proc_info.error = result.error
        if on_complete is not None:
            on_complete(
                TrackedProcCompletion(
                    proc_info=proc_info,
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return proc_info

    app._submit_session_worker.side_effect = submit
    app._submit_tracked_proc.side_effect = (
        lambda proc_type, cl_name, project_file, proc_callable, **kwargs: submit(
            proc_type,
            proc_callable,
            cl_name=cl_name,
            project_file=project_file,
            **kwargs,
        )
    )
    return submitted
