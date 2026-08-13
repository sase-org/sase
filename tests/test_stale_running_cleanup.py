"""Tests for stale RUNNING entry cleanup functionality."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from sase.ace.scheduler.stale_running_cleanup import (
    _get_all_project_files,
    cleanup_stale_running_entries,
)
from sase.running_field import WorkspaceClaim


def test_cleanup_keeps_running_process_entries() -> None:
    """Test that entries with running PIDs are kept."""
    claims = [
        WorkspaceClaim(workspace_num=1, workflow="crs", cl_name="feature_a", pid=12345),
        WorkspaceClaim(workspace_num=2, workflow="run", cl_name="feature_b", pid=67890),
    ]

    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files"
        ) as mock_get_files,
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces"
        ) as mock_get_claims,
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running"
        ) as mock_is_running,
        patch(
            "sase.ace.scheduler.stale_running_cleanup.release_workspace"
        ) as mock_release,
    ):
        mock_get_files.return_value = [
            "/home/user/.sase/projects/myproject/myproject.sase"
        ]
        mock_get_claims.return_value = claims
        # Both PIDs running
        mock_is_running.return_value = True

        released = cleanup_stale_running_entries()

        assert released == 0
        mock_release.assert_not_called()


def test_cleanup_logs_entry_without_cl_name() -> None:
    """Test log message for entry without Patch name."""
    claims = [
        WorkspaceClaim(workspace_num=2, workflow="run", cl_name=None, pid=54321),
    ]

    log_fn = MagicMock()

    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files"
        ) as mock_get_files,
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces"
        ) as mock_get_claims,
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running"
        ) as mock_is_running,
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace"),
    ):
        mock_get_files.return_value = ["/home/user/.sase/projects/proj/proj.sase"]
        mock_get_claims.return_value = claims
        mock_is_running.return_value = False

        cleanup_stale_running_entries(log_fn=log_fn)

        log_fn.assert_called_once()
        log_msg = log_fn.call_args[0][0]
        assert "Released stale workspace #2" in log_msg
        assert "run" in log_msg
        assert "for CL" not in log_msg  # No Patch name


def test_get_all_project_files_nonexistent_dir() -> None:
    """Test _get_all_project_files when projects dir doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Point home to temp dir with no .sase/projects directory
        fake_home = Path(tmpdir)
        with patch.dict("os.environ", {"SASE_HOME": str(fake_home / ".sase")}):
            result = _get_all_project_files()

            assert result == []


def test_get_all_project_files_finds_project_spec_files() -> None:
    """Test _get_all_project_files finds project spec files in project dirs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_home = Path(tmpdir)
        projects_dir = fake_home / ".sase" / "projects"
        projects_dir.mkdir(parents=True)

        # Create proj1 with project spec file
        proj1_dir = projects_dir / "proj1"
        proj1_dir.mkdir()
        (proj1_dir / "proj1.sase").write_text("# test")

        # Create proj2 without project spec file
        proj2_dir = projects_dir / "proj2"
        proj2_dir.mkdir()

        # Create a regular file (not a directory)
        (projects_dir / "somefile.txt").write_text("not a dir")

        with patch.dict("os.environ", {"SASE_HOME": str(fake_home / ".sase")}):
            result = _get_all_project_files()

            # Should only find proj1.sase
            assert len(result) == 1
            assert "proj1.sase" in result[0]


def test_cleanup_releases_each_dead_claim_by_identity() -> None:
    """Shared dead PIDs release every matching claim without touching live ones."""
    project_file = "/home/user/.sase/projects/myproject/myproject.sase"
    claims = [
        WorkspaceClaim(
            workspace_num=10,
            workflow="ace(run)-260101_120000",
            cl_name="feature_a",
            pid=11111,
        ),
        WorkspaceClaim(
            workspace_num=11,
            workflow="ace(run)-260101_120001",
            cl_name="feature_b",
            pid=11111,
        ),
        WorkspaceClaim(
            workspace_num=12,
            workflow="ace(run)-260101_120002",
            cl_name="feature_c",
            pid=22222,
        ),
    ]

    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=claims,
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            side_effect=lambda pid: pid == 22222,
        ),
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        released = cleanup_stale_running_entries()

    assert released == 2
    assert release.call_args_list == [
        call(project_file, 10, "ace(run)-260101_120000", "feature_a"),
        call(project_file, 11, "ace(run)-260101_120001", "feature_b"),
    ]


def test_cleanup_skips_pinned_entries() -> None:
    """Test that pinned entries are not released even if their PID is dead."""
    claims = [
        WorkspaceClaim(
            workspace_num=1,
            workflow="crs",
            cl_name="pinned_feature",
            pid=11111,
            pinned=True,
        ),
        WorkspaceClaim(
            workspace_num=2,
            workflow="run",
            cl_name="unpinned_feature",
            pid=22222,
            pinned=False,
        ),
    ]

    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files"
        ) as mock_get_files,
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces"
        ) as mock_get_claims,
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running"
        ) as mock_is_running,
        patch(
            "sase.ace.scheduler.stale_running_cleanup.release_workspace"
        ) as mock_release,
    ):
        mock_get_files.return_value = [
            "/home/user/.sase/projects/myproject/myproject.sase"
        ]
        mock_get_claims.return_value = claims
        # Both PIDs are dead
        mock_is_running.return_value = False

        released = cleanup_stale_running_entries()

        # Only the unpinned entry should be released
        assert released == 1
        mock_release.assert_called_once_with(
            "/home/user/.sase/projects/myproject/myproject.sase",
            2,
            "run",
            "unpinned_feature",
        )
        # is_process_running should only be called for the unpinned entry
        mock_is_running.assert_called_once_with(22222)


def test_cleanup_keeps_held_workspace_while_artifacts_exist() -> None:
    claim = WorkspaceClaim(
        workspace_num=17,
        workflow="run",
        cl_name="feature",
        pid=11111,
        artifacts_timestamp="20260712120000",
        pinned=True,
    )
    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=["/tmp/projects/proj/proj.sase"],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup._held_agent_artifacts_exist",
            return_value=True,
        ),
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 0
    release.assert_not_called()


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
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
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
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
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
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
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
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 1
    release.assert_called_once_with(project_file, 10, "ace-monitor", "feature")


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
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[monitor_claim, other_claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.monitor.store.read_monitor_marker",
            return_value=MagicMock(is_terminal=True),
        ) as read_marker,
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        released = cleanup_stale_running_entries(skip_monitor_claims=True)

    assert released == 1
    release.assert_called_once_with(project_file, 11, "run", "other")
    read_marker.assert_not_called()


def test_cleanup_releases_held_workspace_after_artifacts_are_deleted() -> None:
    claim = WorkspaceClaim(
        workspace_num=17,
        workflow="run",
        cl_name="feature",
        pid=11111,
        artifacts_timestamp="20260712120000",
        pinned=True,
    )
    project_file = "/tmp/projects/proj/proj.sase"
    with (
        patch(
            "sase.ace.scheduler.stale_running_cleanup._get_all_project_files",
            return_value=[project_file],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.scheduler.stale_running_cleanup._held_agent_artifacts_exist",
            return_value=False,
        ),
        patch("sase.ace.scheduler.stale_running_cleanup.release_workspace") as release,
    ):
        assert cleanup_stale_running_entries() == 1
    release.assert_called_once_with(project_file, 17, "run", "feature")
