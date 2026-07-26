"""TUI bridge coverage for detached epic launches."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.agents._notification_epic_launch import (
    submit_epic_launch_task,
)
from sase.notifications import Notification


def _notification(tmp_path: Path, plan_file: Path) -> Notification:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    return Notification(
        id="epic-notification",
        timestamp="2026-07-15T12:00:00+00:00",
        sender="plan",
        action="PlanApproval",
        files=[str(plan_file)],
        action_data={
            "project_dir": str(tmp_path / "workspace"),
            "agent_project_file": str(tmp_path / "demo.sase"),
            "agent_cl_name": "demo",
            "artifacts_dir": str(artifacts),
        },
    )


def test_tui_epic_launch_submits_the_shared_detached_task(tmp_path: Path) -> None:
    plan = tmp_path / "epic plan.md"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    notification = _notification(tmp_path, plan)
    app = MagicMock()

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_epic_launch."
            "resolve_epic_launch_cwd",
            return_value=workspace,
        ) as resolve_cwd,
        patch(
            "sase.ace.tui.actions.agents._notification_epic_launch."
            "submit_detached_epic_launch_task",
            return_value=SimpleNamespace(task_id="task"),
        ) as submit,
    ):
        owned = submit_epic_launch_task(
            app,
            notification,
            plan_file=str(plan),
            phase_count=2,
        )

    assert owned is True
    resolve_cwd.assert_called_once_with(
        str(workspace),
        agent_project_file=str(tmp_path / "demo.sase"),
    )
    submit.assert_called_once_with(
        str(plan),
        cwd=workspace,
        artifacts_dir=str(tmp_path / "artifacts"),
        cl_name="demo",
        origin="ace",
    )
    app._submit_tracked_task.assert_not_called()


def test_tui_epic_launch_accepts_project_file_without_project_dir(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "epic.md"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    notification = _notification(tmp_path, plan)
    notification.action_data.pop("project_dir")

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_epic_launch."
            "resolve_epic_launch_cwd",
            return_value=workspace,
        ) as resolve_cwd,
        patch(
            "sase.ace.tui.actions.agents._notification_epic_launch."
            "submit_detached_epic_launch_task",
        ),
    ):
        owned = submit_epic_launch_task(
            MagicMock(),
            notification,
            plan_file=str(plan),
            phase_count=1,
        )

    assert owned is True
    resolve_cwd.assert_called_once_with(
        None,
        agent_project_file=str(tmp_path / "demo.sase"),
    )


def test_tui_epic_launch_declines_without_project_identity(tmp_path: Path) -> None:
    plan = tmp_path / "epic.md"
    notification = _notification(tmp_path, plan)
    notification.action_data.pop("project_dir")
    notification.action_data.pop("agent_project_file")

    with patch(
        "sase.ace.tui.actions.agents._notification_epic_launch."
        "submit_detached_epic_launch_task"
    ) as submit:
        owned = submit_epic_launch_task(
            MagicMock(),
            notification,
            plan_file=str(plan),
            phase_count=1,
        )

    assert owned is False
    submit.assert_not_called()


def test_tui_epic_launch_reports_submission_failure(tmp_path: Path) -> None:
    plan = tmp_path / "epic.md"
    notification = _notification(tmp_path, plan)

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_epic_launch."
            "resolve_epic_launch_cwd",
            return_value=tmp_path,
        ),
        patch(
            "sase.ace.tui.actions.agents._notification_epic_launch."
            "submit_detached_epic_launch_task",
            side_effect=RuntimeError("task store unavailable"),
        ),
    ):
        owned = submit_epic_launch_task(
            MagicMock(),
            notification,
            plan_file=str(plan),
            phase_count=1,
        )

    assert owned is False
