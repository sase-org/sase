"""Tests for stale RUNNING entry cleanup functionality."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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
            "/home/user/.sase/projects/myproject/myproject.gp"
        ]
        mock_get_claims.return_value = claims
        # Both PIDs running
        mock_is_running.return_value = True

        released = cleanup_stale_running_entries()

        assert released == 0
        mock_release.assert_not_called()


def test_cleanup_logs_entry_without_cl_name() -> None:
    """Test log message for entry without CL name."""
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
        mock_get_files.return_value = ["/home/user/.sase/projects/proj/proj.gp"]
        mock_get_claims.return_value = claims
        mock_is_running.return_value = False

        cleanup_stale_running_entries(log_fn=log_fn)

        log_fn.assert_called_once()
        log_msg = log_fn.call_args[0][0]
        assert "Released stale workspace #2" in log_msg
        assert "run" in log_msg
        assert "for CL" not in log_msg  # No CL name


def test_get_all_project_files_nonexistent_dir() -> None:
    """Test _get_all_project_files when projects dir doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Point home to temp dir with no .sase/projects directory
        fake_home = Path(tmpdir)
        with patch("sase.ace.scheduler.stale_running_cleanup.Path") as mock_path:
            mock_path.home.return_value = fake_home

            result = _get_all_project_files()

            assert result == []


def test_get_all_project_files_finds_gp_files() -> None:
    """Test _get_all_project_files finds .gp files in project dirs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_home = Path(tmpdir)
        projects_dir = fake_home / ".sase" / "projects"
        projects_dir.mkdir(parents=True)

        # Create proj1 with .gp file
        proj1_dir = projects_dir / "proj1"
        proj1_dir.mkdir()
        (proj1_dir / "proj1.gp").write_text("# test")

        # Create proj2 without .gp file
        proj2_dir = projects_dir / "proj2"
        proj2_dir.mkdir()

        # Create a regular file (not a directory)
        (projects_dir / "somefile.txt").write_text("not a dir")

        with patch("sase.ace.scheduler.stale_running_cleanup.Path") as mock_path:
            mock_path.home.return_value = fake_home

            result = _get_all_project_files()

            # Should only find proj1.gp
            assert len(result) == 1
            assert "proj1.gp" in result[0]


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
            "/home/user/.sase/projects/myproject/myproject.gp"
        ]
        mock_get_claims.return_value = claims
        # Both PIDs are dead
        mock_is_running.return_value = False

        released = cleanup_stale_running_entries()

        # Only the unpinned entry should be released
        assert released == 1
        mock_release.assert_called_once_with(
            "/home/user/.sase/projects/myproject/myproject.gp",
            2,
            "run",
            "unpinned_feature",
        )
        # is_process_running should only be called for the unpinned entry
        mock_is_running.assert_called_once_with(22222)
