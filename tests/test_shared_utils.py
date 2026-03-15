"""Tests for sase.shared_utils module."""

import os
import string
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sase.sase_utils import run_shell_command
from sase.shared_utils import (
    _finalize_log_file,
    _initialize_log_file,
    apply_section_marker_handling,
    content_ends_with_markdown_heading,
    create_artifacts_directory,
    ensure_str_content,
    finalize_sase_log,
    generate_workflow_tag,
    initialize_sase_log,
    run_bam_command,
)


def test_ensure_str_content_with_list() -> None:
    """Test that list content is converted to string."""
    content: list[str | dict[str, str]] = ["part1", "part2", {"key": "value"}]
    result = ensure_str_content(content)
    assert isinstance(result, str)
    assert "part1" in result
    assert "part2" in result


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


@patch("sase.shared_utils.run_shell_command")
def test_run_bam_command_success(mock_run_cmd: MagicMock) -> None:
    """Test that bam command is run successfully."""
    # This should not raise an exception
    run_bam_command("Test completed")
    mock_run_cmd.assert_called_once()


@patch("sase.shared_utils.run_shell_command")
def test_run_bam_command_exception(mock_run_cmd: MagicMock) -> None:
    """Test that bam command exceptions are handled gracefully."""
    mock_run_cmd.side_effect = Exception("bam not found")

    # Should not raise an exception
    run_bam_command("Test message")


@patch("sase.shared_utils.run_shell_command")
def test_create_artifacts_directory_without_project_name(
    mock_run_cmd: MagicMock,
) -> None:
    """Test creating artifacts directory when project_name is None."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "auto-project"
    mock_run_cmd.return_value = mock_result

    artifacts_dir = create_artifacts_directory("test-workflow")

    # Verify workspace_name was called
    mock_run_cmd.assert_called_once_with("workspace_name", capture_output=True)

    # Check directory format includes the auto-detected project name
    expanded_home = str(Path.home())
    expected_prefix = (
        f"{expanded_home}/.sase/projects/auto-project/artifacts/test-workflow/"
    )
    assert artifacts_dir.startswith(expected_prefix)

    # Cleanup
    import shutil

    project_dir = Path.home() / ".sase" / "projects" / "auto-project"
    if project_dir.exists():
        shutil.rmtree(project_dir)


@patch("sase.shared_utils.run_shell_command")
def test_create_artifacts_directory_workspace_name_fails(
    mock_run_cmd: MagicMock,
) -> None:
    """Test that RuntimeError is raised when workspace_name fails."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "workspace_name not found"
    mock_run_cmd.return_value = mock_result

    with pytest.raises(RuntimeError) as exc_info:
        create_artifacts_directory("test-workflow")

    assert "Failed to get project name" in str(exc_info.value)
    assert "workspace_name not found" in str(exc_info.value)


# Tests for get_sase_log_file
# Tests for _initialize_log_file
@patch("sase.shared_utils.print_status")
def test_initialize_log_file_error(mock_print_status: MagicMock) -> None:
    """Test _initialize_log_file handles write errors gracefully."""
    _initialize_log_file("/nonexistent/dir/file.md", "content", "Test op")
    mock_print_status.assert_called_once()
    call_msg = mock_print_status.call_args[0][0]
    assert "Failed" in call_msg


# Tests for _finalize_log_file
@patch("sase.shared_utils.print_status")
def test_finalize_log_file_error(mock_print_status: MagicMock) -> None:
    """Test _finalize_log_file handles errors gracefully."""
    _finalize_log_file("/nonexistent/dir/file.md", "content", "Test op")
    mock_print_status.assert_called_once()
    call_msg = mock_print_status.call_args[0][0]
    assert "Failed" in call_msg


# Tests for apply_section_marker_handling
def test_apply_section_marker_handling_hr_marker_only_not_at_line_start() -> None:
    """Test standalone --- marker not at line start is stripped (no newlines added for empty)."""
    content = "---"
    result = apply_section_marker_handling(content, is_at_line_start=False)
    assert result == ""


def test_apply_section_marker_handling_hr_marker_with_content() -> None:
    """Test --- marker at line start prepends \\n for paragraph break."""
    content = "---\nActual content"
    result = apply_section_marker_handling(content, is_at_line_start=True)
    assert result == "\nActual content"


# Tests for content_ends_with_markdown_heading
def test_content_ends_with_markdown_heading_empty() -> None:
    """Test that empty content returns False."""
    assert content_ends_with_markdown_heading("") is False


# Tests for convert_timestamp_to_artifacts_format
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
    expanded_home = str(Path.home())
    expected_path = (
        f"{expanded_home}/.sase/projects/{project_name}"
        f"/artifacts/{workflow_name}/{expected_suffix}"
    )
    assert artifacts_dir == expected_path

    # Check directory exists
    assert Path(artifacts_dir).exists()

    # Cleanup
    import shutil

    project_dir = Path.home() / ".sase" / "projects" / project_name
    shutil.rmtree(project_dir)
