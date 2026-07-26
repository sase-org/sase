"""Tracked TUI epic-launch task tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


def test_tracked_epic_launch_streams_and_backfills_metadata(tmp_path: Path) -> None:
    plan = tmp_path / "epic plan.md"
    plan.write_text("# Epic\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    notification = _notification(tmp_path, plan)

    app = MagicMock()
    app._task_queue.get_running_for_key.return_value = None
    app._submit_tracked_task.return_value = SimpleNamespace(task_id="task")
    with (
        patch(
            "sase.ace.tui.actions.agents._notification_epic_launch."
            "resolve_epic_launch_cwd",
            return_value=workspace,
        ) as resolve_cwd,
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation",
        ),
    ):
        owned = submit_epic_launch_task(
            app,
            notification,
            plan_file=str(plan),
            phase_count=2,
        )
        assert owned is True
        task_args = app._submit_tracked_task.call_args.args
        task_kwargs = app._submit_tracked_task.call_args.kwargs
        assert task_args[:3] == (
            "epic-launch",
            "demo",
            str(tmp_path / "demo.sase"),
        )
        assert task_kwargs["display_name"] == "Epic launch: epic plan"
        assert task_kwargs["dedup_key"].startswith("epic-launch:")

        reporter = MagicMock()
        reporter.run.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "✓ Archived        /plans/202607/epic plan.md (committed)\n"
                "Epic: sase-64\n"
            ),
        )
        task_result = task_args[3](reporter)
    assert task_result.success is True
    resolve_cwd.assert_called_once_with(
        str(tmp_path / "workspace"),
        agent_project_file=str(tmp_path / "demo.sase"),
    )
    reporter.run.assert_called_once_with(
        ["sase", "bead", "work", str(plan), "--yes-to-all"],
        cwd=workspace,
    )

    task_kwargs["on_complete"](
        SimpleNamespace(success=True, payload=task_result.payload)
    )
    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["epic_bead_id"] == "sase-64"
    assert meta["sdd_plan_path"] == "/plans/202607/epic plan.md"
    assert meta["plan_committed"] is True
    app.notify.assert_called_with(
        "2 phase agents + land agent",
        title="Epic sase-64 launched",
    )


def test_tracked_epic_launch_accepts_project_file_without_project_dir(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "epic.md"
    plan.write_text("# Epic\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    notification = _notification(tmp_path, plan)
    notification.action_data.pop("project_dir")

    app = MagicMock()
    app._task_queue.get_running_for_key.return_value = None
    app._submit_tracked_task.return_value = SimpleNamespace(task_id="task")
    with patch(
        "sase.ace.tui.actions.agents._notification_epic_launch.resolve_epic_launch_cwd",
        return_value=workspace,
    ) as resolve_cwd:
        owned = submit_epic_launch_task(
            app,
            notification,
            plan_file=str(plan),
            phase_count=1,
        )

        assert owned is True
        task_args = app._submit_tracked_task.call_args.args
        assert task_args[:3] == (
            "epic-launch",
            "demo",
            str(tmp_path / "demo.sase"),
        )
        resolve_cwd.assert_not_called()

        reporter = MagicMock()
        reporter.run.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout="Epic: sase-64\n",
        )
        task_args[3](reporter)
        resolve_cwd.assert_called_once_with(
            None,
            agent_project_file=str(tmp_path / "demo.sase"),
        )


@pytest.mark.parametrize(
    ("returncode", "output"),
    [
        (1, "Epic: sase-64\n"),
        (0, "✓ Archived        /plans/202607/epic.md (committed)\n"),
    ],
    ids=["failed-command", "missing-epic-id"],
)
def test_tracked_epic_launch_does_not_backfill_unsuccessful_output(
    tmp_path: Path,
    returncode: int,
    output: str,
) -> None:
    plan = tmp_path / "epic.md"
    plan.write_text("# Epic\n", encoding="utf-8")
    notification = _notification(tmp_path, plan)
    app = MagicMock()
    app._task_queue.get_running_for_key.return_value = None
    app._submit_tracked_task.return_value = SimpleNamespace(task_id="task")

    with patch(
        "sase.ace.tui.actions.agents._notification_epic_launch.resolve_epic_launch_cwd",
        return_value=tmp_path,
    ):
        owned = submit_epic_launch_task(
            app,
            notification,
            plan_file=str(plan),
            phase_count=1,
        )
        assert owned is True
        work = app._submit_tracked_task.call_args.args[3]
        reporter = MagicMock()
        reporter.run.return_value = subprocess.CompletedProcess(
            [],
            returncode,
            stdout=output,
        )

        result = work(reporter)

    assert result.success is False
    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert "epic_bead_id" not in meta
    assert "epic_started_at" not in meta


def test_tracked_epic_launch_deduplicates_by_plan_path(tmp_path: Path) -> None:
    plan = tmp_path / "epic.md"
    notification = _notification(tmp_path, plan)
    app = MagicMock()
    app._task_queue.get_running_for_key.return_value = SimpleNamespace(
        task_id="existing"
    )

    with patch(
        "sase.ace.tui.actions.agents._notification_epic_launch.resolve_epic_launch_cwd",
        return_value=tmp_path,
    ):
        owned = submit_epic_launch_task(
            app,
            notification,
            plan_file=str(plan),
            phase_count=1,
        )

    assert owned is True
    app._submit_tracked_task.assert_not_called()


def test_tracked_epic_launch_reports_workspace_resolution_failure(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "epic.md"
    notification = _notification(tmp_path, plan)
    app = MagicMock()
    app._task_queue.get_running_for_key.return_value = None
    app._submit_tracked_task.return_value = SimpleNamespace(task_id="task")

    with patch(
        "sase.ace.tui.actions.agents._notification_epic_launch.resolve_epic_launch_cwd",
        side_effect=ValueError("invalid project identity"),
    ):
        owned = submit_epic_launch_task(
            app,
            notification,
            plan_file=str(plan),
            phase_count=1,
        )
        task_args = app._submit_tracked_task.call_args.args
        task_kwargs = app._submit_tracked_task.call_args.kwargs
        reporter = MagicMock()
        task_result = task_args[3](reporter)

    assert owned is True
    assert task_result.success is False
    assert "invalid project identity" in task_result.message
    reporter.run.assert_not_called()

    task_kwargs["on_complete"](
        SimpleNamespace(success=False, payload=None),
    )
    app.notify.assert_called_once_with(
        f"See the Tasks tab for output. Resume with: "
        f"sase bead work {plan} --yes-to-all",
        title="Epic launch failed",
        severity="error",
        timeout=15,
    )
