"""Tests for sase.artifacts module."""

import os
import string
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sase.core.shell import run_shell_command
from sase.artifacts import (
    _finalize_log_file,
    _initialize_log_file,
    create_artifacts_directory,
    finalize_sase_log,
    generate_workflow_tag,
    initialize_sase_log,
    run_bam_command,
)


def test_run_shell_command_success() -> None:
    """Test that successful shell command returns proper result."""
    result = run_shell_command("echo 'test'", capture_output=True)
    assert result.returncode == 0
    assert "test" in result.stdout


def test_generate_workflow_tag() -> None:
    """Test that workflow tag is generated with correct format."""
    tag = generate_workflow_tag()

    # Should be 3 characters
    assert len(tag) == 3

    # Should only contain digits and uppercase letters
    valid_chars = string.digits + string.ascii_uppercase
    assert all(c in valid_chars for c in tag)


def test_finalize_sase_log() -> None:
    """Test that sase.md log is finalized correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Initialize first
        initialize_sase_log(tmpdir, "crs", "XYZ")

        # Finalize with success
        finalize_sase_log(tmpdir, "crs", "XYZ", success=True)

        log_file = os.path.join(tmpdir, "sase.md")
        with open(log_file, encoding="utf-8") as f:
            content = f.read()

        assert "Workflow Completed" in content
        assert "SUCCESS" in content
        assert "crs" in content
        assert "XYZ" in content


@patch("sase.artifacts.run_shell_command")
def test_run_bam_command_success(mock_run_cmd: MagicMock) -> None:
    """Test that bam command is run successfully."""
    # This should not raise an exception
    run_bam_command("Test completed")
    mock_run_cmd.assert_called_once()


@patch("sase.artifacts.run_shell_command")
def test_run_bam_command_exception(mock_run_cmd: MagicMock) -> None:
    """Test that bam command exceptions are handled gracefully."""
    mock_run_cmd.side_effect = Exception("bam not found")

    # Should not raise an exception
    run_bam_command("Test message")


@patch("sase.workspace_provider.get_workspace_name", return_value="auto-project")
def test_create_artifacts_directory_without_project_name(
    mock_get_name: MagicMock,
) -> None:
    """Test creating artifacts directory when project_name is None."""
    artifacts_dir = create_artifacts_directory("test-workflow")

    mock_get_name.assert_called_once()

    # Check directory format includes the auto-detected project name
    expected_prefix = str(
        Path("~/.sase/projects/auto-project/artifacts/test-workflow/").expanduser()
    )
    assert artifacts_dir.startswith(expected_prefix)

    # Cleanup
    import shutil

    project_dir = Path("~/.sase/projects/auto-project").expanduser()
    if project_dir.exists():
        shutil.rmtree(project_dir)


@patch("sase.workspace_provider.get_workspace_name", return_value=None)
def test_create_artifacts_directory_workspace_name_fails(
    mock_get_name: MagicMock,
) -> None:
    """Test that RuntimeError is raised when workspace name cannot be detected."""
    with pytest.raises(RuntimeError, match="Failed to detect project name"):
        create_artifacts_directory("test-workflow")


# Tests for _initialize_log_file
@patch("sase.artifacts.print_status")
def test_initialize_log_file_error(mock_print_status: MagicMock) -> None:
    """Test _initialize_log_file handles write errors gracefully."""
    _initialize_log_file("/nonexistent/dir/file.md", "content", "Test op")
    mock_print_status.assert_called_once()
    call_msg = mock_print_status.call_args[0][0]
    assert "Failed" in call_msg


# Tests for _finalize_log_file
@patch("sase.artifacts.print_status")
def test_finalize_log_file_error(mock_print_status: MagicMock) -> None:
    """Test _finalize_log_file handles errors gracefully."""
    _finalize_log_file("/nonexistent/dir/file.md", "content", "Test op")
    mock_print_status.assert_called_once()
    call_msg = mock_print_status.call_args[0][0]
    assert "Failed" in call_msg


# Tests for create_artifacts_directory with timestamp parameter
def test_create_artifacts_directory_with_timestamp() -> None:
    """Test that pre-existing timestamp is used instead of generating new one."""
    project_name = "test-project-ts"
    workflow_name = "test-workflow"
    timestamp = "251227_143052"
    artifacts_dir = create_artifacts_directory(
        workflow_name, project_name, timestamp=timestamp
    )

    # Check that the directory uses the converted timestamp
    expected_suffix = "20251227143052"
    assert artifacts_dir.endswith(expected_suffix)

    # Verify format: ~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>
    expected_path = str(
        Path(
            f"~/.sase/projects/{project_name}"
            f"/artifacts/{workflow_name}/{expected_suffix}"
        ).expanduser()
    )
    assert artifacts_dir == expected_path

    # Check directory exists
    assert Path(artifacts_dir).exists()

    # Cleanup
    import shutil

    project_dir = Path(f"~/.sase/projects/{project_name}").expanduser()
    shutil.rmtree(project_dir)
