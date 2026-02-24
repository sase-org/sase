"""Tests for sase_utils module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.sase_utils import (
    changespec_name_to_branch,
    get_next_suffix_number,
    get_workspace_directory_for_changespec,
    run_workspace_command,
    shorten_path,
    strip_hook_prefix,
)


def test_shorten_path_partial_home_match() -> None:
    """Test shorten_path with path that doesn't start with home."""
    home = str(Path.home())
    # Path that contains home directory but not at start
    path = f"/prefix{home}/file.txt"
    result = shorten_path(path)
    # Should still replace the home part
    assert result == "/prefix~/file.txt"


def test_get_workspace_directory_for_changespec_extracts_basename() -> None:
    """Test that get_workspace_directory_for_changespec extracts project basename."""
    mock_changespec = MagicMock()
    mock_changespec.file_path = "/some/path/my_project.gp"
    mock_changespec.project_basename = "my_project"

    with patch("sase.running_field.get_workspace_directory") as mock_get_ws:
        mock_get_ws.return_value = "/workspace/my_project"
        get_workspace_directory_for_changespec(mock_changespec)
        # Should extract "my_project" from "my_project.gp"
        mock_get_ws.assert_called_once_with("my_project")


# Tests for strip_hook_prefix
def test_strip_hook_prefix_dollar() -> None:
    """Test strip_hook_prefix removes $ prefix."""
    assert strip_hook_prefix("$sase_hg_test") == "sase_hg_test"


# Tests for has_suffix


# Tests for get_next_suffix_number


def test_get_next_suffix_number_ignores_other_bases() -> None:
    """Test get_next_suffix_number ignores names with different bases."""
    existing = {"other__1", "other__2", "feature__1"}
    result = get_next_suffix_number("feature", existing)
    assert result == 2  # Only considers feature__*, so next is 2


# Tests for run_workspace_command


def test_run_workspace_command_failure() -> None:
    """Test run_workspace_command returns failure on non-zero exit code."""
    with patch("sase.sase_utils.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="some error", stdout="")
        success, error = run_workspace_command(["sase_hg_prune", "foo"], "/tmp")

    assert success is False
    assert error is not None
    assert "sase_hg_prune failed" in error
    assert "some error" in error


def test_run_workspace_command_command_not_found() -> None:
    """Test run_workspace_command handles FileNotFoundError."""
    with patch("sase.sase_utils.subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError()
        success, error = run_workspace_command(["nonexistent_cmd"], "/tmp")

    assert success is False
    assert error == "nonexistent_cmd command not found"


def test_run_workspace_command_no_capture() -> None:
    """Test run_workspace_command with capture_output=False."""
    with patch("sase.sase_utils.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        success, error = run_workspace_command(
            ["sase", "commit"], "/tmp", capture_output=False
        )

    assert success is True
    assert error is None
    mock_run.assert_called_once_with(
        ["sase", "commit"], cwd="/tmp", capture_output=False, text=True, check=False
    )


# Tests for changespec_name_to_branch


def test_changespec_name_to_branch_no_prefix() -> None:
    """Name without project prefix falls through to hyphen conversion."""
    assert changespec_name_to_branch("dull_basin__1", "sase") == "dull-basin"
