"""Tests for ``sase bead work`` rollback cleanup."""

from __future__ import annotations

import signal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.agent.launch_types import AgentLaunchResult
from sase.bead.cli_work_cleanup import rollback_work_launch


def _launch_result() -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=1234,
        workspace_num=10,
        workspace_dir="/workspace/10",
        output_path="/tmp/out.txt",
        project_file="/tmp/.sase/projects/sase/sase.sase",
        project_name="sase",
        workflow_name="ace(run)-260101_120000",
        cl_name="sase",
        timestamp="260101_120000",
    )


def test_rollback_work_launch_uses_identity_aware_result_cleanup() -> None:
    proj = SimpleNamespace(update=MagicMock(), unmark_ready_to_work=MagicMock())
    result = _launch_result()

    with (
        patch(
            "sase.agent.partial_launch.rollback_partial_launch_results"
        ) as rollback_results,
        patch("sase.bead.cli_work_cleanup.os.kill") as kill,
    ):
        rollback_work_launch(
            proj,
            "epic-1",
            marked_ready_this_run=True,
            launched_pids=[result.pid],
            launched_results=[result],
        )

    rollback_results.assert_called_once_with([result])
    kill.assert_not_called()
    proj.unmark_ready_to_work.assert_not_called()


def test_rollback_work_launch_keeps_pid_fallback() -> None:
    proj = SimpleNamespace(update=MagicMock(), unmark_ready_to_work=MagicMock())

    with patch("sase.bead.cli_work_cleanup.os.kill") as kill:
        rollback_work_launch(
            proj,
            "epic-1",
            marked_ready_this_run=True,
            launched_pids=[1234],
        )

    kill.assert_called_once_with(1234, signal.SIGTERM)
    proj.unmark_ready_to_work.assert_not_called()
