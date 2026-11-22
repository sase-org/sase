"""Terminal member claim cases for stale-running cleanup."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.scheduler.stale_running_cleanup import cleanup_stale_running_entries
from sase.running_field import WorkspaceClaim


def _recent_stamp(*, days_ago: int = 2) -> str:
    """Return a claim timestamp safely inside the default held-claim TTL."""
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d%H%M%S")


def test_cleanup_keeps_dead_monitor_claim_when_member_not_terminal() -> None:
    """A dead-pid ace-monitor claim is not released until the member is terminal."""
    claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-monitor",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20260813125344"),
        ),
        patch(
            "sase.monitor.store.read_monitor_marker",
            return_value=MagicMock(is_terminal=False),
        ),
        patch("sase.ace.scheduler.stale_running_sweep.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 0
    release.assert_not_called()


def test_cleanup_releases_dead_monitor_claim_once_member_is_terminal() -> None:
    """A dead-pid ace-monitor claim releases once the member's own record settles."""
    claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-monitor",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20260813125344"),
        ),
        patch(
            "sase.monitor.store.read_monitor_marker",
            return_value=MagicMock(is_terminal=True),
        ),
        patch("sase.ace.scheduler.stale_running_sweep.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 1
    release.assert_called_once_with(
        project_file,
        10,
        "ace-monitor",
        "feature",
        caller_tag="stale-cleanup",
        expected_pid=claim.pid,
        artifacts_timestamp=claim.artifacts_timestamp,
    )


def test_cleanup_keeps_dead_gate_claim_when_member_not_terminal() -> None:
    """A dead-pid ace-gate claim is held while its gate shell is pending."""
    claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-gate",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp=_recent_stamp(),
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20260813125344"),
        ),
        patch(
            "sase.gate_turn.store.read_gate_turn_marker",
            return_value=MagicMock(is_terminal=False),
        ),
        patch("sase.ace.scheduler.stale_running_sweep.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 0
    release.assert_not_called()


def test_cleanup_releases_dead_gate_claim_once_member_is_terminal() -> None:
    """A dead-pid ace-gate claim releases only after shell settlement."""
    claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-gate",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20260813125344"),
        ),
        patch(
            "sase.gate_turn.store.read_gate_turn_marker",
            return_value=MagicMock(is_terminal=True),
        ),
        patch("sase.ace.scheduler.stale_running_sweep.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 1
    release.assert_called_once_with(
        project_file,
        10,
        "ace-gate",
        "feature",
        caller_tag="stale-cleanup",
        expected_pid=claim.pid,
        artifacts_timestamp=claim.artifacts_timestamp,
    )


def test_cleanup_skip_monitor_claims_leaves_ace_monitor_claims_untouched() -> None:
    """skip_monitor_claims=True never releases ace-monitor claims this sweep."""
    monitor_claim = WorkspaceClaim(
        workspace_num=10,
        workflow="ace-monitor",
        cl_name="feature",
        pid=33333,
        artifacts_timestamp="20260813125344",
    )
    other_claim = WorkspaceClaim(
        workspace_num=11,
        workflow="run",
        cl_name="other",
        pid=44444,
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_sweep._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.get_claimed_workspaces",
            return_value=[monitor_claim, other_claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_sweep.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.monitor.store.read_monitor_marker",
            return_value=MagicMock(is_terminal=True),
        ) as read_marker,
        patch("sase.ace.scheduler.stale_running_sweep.release_workspace") as release,
    ):
        released = cleanup_stale_running_entries(skip_monitor_claims=True)

    assert released == 1
    release.assert_called_once_with(
        project_file,
        11,
        "run",
        "other",
        caller_tag="stale-cleanup",
        expected_pid=other_claim.pid,
        artifacts_timestamp=other_claim.artifacts_timestamp,
    )
    read_marker.assert_not_called()
