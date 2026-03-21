"""Tests for sase.workflow_utils module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.workflows.utils import (
    _get_changed_test_targets,
    add_test_hooks_if_available,
    get_changespec_from_file,
    get_cl_name_from_branch,
    get_initial_hooks_for_changespec,
    get_project_from_workspace,
)


def test__get_changed_test_targets_whitespace_only() -> None:
    """Test that None is returned when command returns only whitespace."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "   \n\n  "

    with patch("sase.workflows.utils.subprocess.run", return_value=mock_result):
        result = _get_changed_test_targets()

    assert result is None


def test__get_changed_test_targets_command_fails() -> None:
    """Test that None is returned when command fails."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Error"

    with patch("sase.workflows.utils.subprocess.run", return_value=mock_result):
        result = _get_changed_test_targets()

    assert result is None


def test__get_changed_test_targets_command_not_found() -> None:
    """Test that None is returned when command is not found."""
    with patch(
        "sase.workflows.utils.subprocess.run",
        side_effect=FileNotFoundError("changed_test_targets not found"),
    ):
        result = _get_changed_test_targets()

    assert result is None


def test__get_changed_test_targets_verbose_logs_success() -> None:
    """Test that no log is printed when command succeeds with verbose=True."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "//foo:test1"

    with (
        patch("sase.workflows.utils.subprocess.run", return_value=mock_result),
        patch("sase.rich_utils.print_status") as mock_print_status,
    ):
        result = _get_changed_test_targets(verbose=True)

    assert result == "//foo:test1"
    mock_print_status.assert_not_called()


def test__get_changed_test_targets_verbose_logs_empty() -> None:
    """Test that log is printed when command returns empty with verbose=True."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""

    with (
        patch("sase.workflows.utils.subprocess.run", return_value=mock_result),
        patch("sase.rich_utils.print_status") as mock_print_status,
    ):
        result = _get_changed_test_targets(verbose=True)

    assert result is None
    mock_print_status.assert_called_once()
    call_args = mock_print_status.call_args
    assert "empty output" in call_args[0][0]


def test__get_changed_test_targets_verbose_logs_failure() -> None:
    """Test that log is printed when command fails with verbose=True."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Error occurred"

    with (
        patch("sase.workflows.utils.subprocess.run", return_value=mock_result),
        patch("sase.rich_utils.print_status") as mock_print_status,
    ):
        result = _get_changed_test_targets(verbose=True)

    assert result is None
    mock_print_status.assert_called_once()
    call_args = mock_print_status.call_args
    assert "failed" in call_args[0][0]


def test_add_test_hooks_if_available_adds_hooks() -> None:
    """Test that function adds hooks when targets are found."""
    with (
        patch(
            "sase.workflows.utils._get_changed_test_targets",
            return_value="//foo:test1 //bar:test2",
        ),
        patch(
            "sase.ace.hooks.add_test_target_hooks_to_changespec", return_value=True
        ) as mock_add_hooks,
        patch("sase.rich_utils.print_status"),
    ):
        result = add_test_hooks_if_available("/fake/project.gp", "cl_name")

    assert result is True
    # No existing_hooks passed - function reads fresh state inside lock
    mock_add_hooks.assert_called_once_with(
        "/fake/project.gp",
        "cl_name",
        ["//foo:test1", "//bar:test2"],
    )


def test_add_test_hooks_if_available_changes_directory() -> None:
    """Test that function changes to workspace_dir when provided."""
    original_dir = "/original/dir"
    workspace_dir = "/workspace/dir"

    with (
        patch("os.getcwd", return_value=original_dir),
        patch("os.chdir") as mock_chdir,
        patch("sase.workflows.utils._get_changed_test_targets", return_value=None),
    ):
        result = add_test_hooks_if_available(
            "/fake/project.gp", "cl_name", workspace_dir=workspace_dir
        )

    assert result is True
    # Should change to workspace_dir and then back to original
    assert mock_chdir.call_count == 2
    mock_chdir.assert_any_call(workspace_dir)
    mock_chdir.assert_any_call(original_dir)


def test_add_test_hooks_if_available_restores_directory_on_error() -> None:
    """Test that function restores directory even if _get_changed_test_targets fails."""
    original_dir = "/original/dir"
    workspace_dir = "/workspace/dir"

    with (
        patch("os.getcwd", return_value=original_dir),
        patch("os.chdir") as mock_chdir,
        patch(
            "sase.workflows.utils._get_changed_test_targets",
            side_effect=Exception("Test error"),
        ),
    ):
        try:
            add_test_hooks_if_available(
                "/fake/project.gp", "cl_name", workspace_dir=workspace_dir
            )
        except Exception:
            pass

    # Should still restore the original directory
    mock_chdir.assert_any_call(original_dir)


def test_add_test_hooks_if_available_returns_false_on_failure() -> None:
    """Test that function returns False when adding hooks fails."""
    with (
        patch(
            "sase.workflows.utils._get_changed_test_targets", return_value="//foo:test1"
        ),
        patch("sase.workflows.utils.get_changespec_from_file", return_value=None),
        patch("sase.ace.hooks.add_test_target_hooks_to_changespec", return_value=False),
        patch("sase.rich_utils.print_status"),
    ):
        result = add_test_hooks_if_available("/fake/project.gp", "cl_name")

    assert result is False


# Tests for get_initial_hooks_for_changespec


def test_get_initial_hooks_for_changespec_returns_config_hooks() -> None:
    """Test that hooks from plugin config are returned."""
    config = {"default_hooks": ["!$sase_google_presubmit", "$sase_google_lint"]}
    with (
        patch("sase.workflows.utils._get_changed_test_targets", return_value=None),
        patch("sase.ace.hooks.defaults.get_vcs_provider_config", return_value=config),
    ):
        result = get_initial_hooks_for_changespec()

    assert "!$sase_google_presubmit" in result
    assert "$sase_google_lint" in result
    assert len(result) == 2


def test_get_initial_hooks_for_changespec_returns_empty_without_config() -> None:
    """Test that no default hooks are returned when no config is set."""
    with (
        patch("sase.workflows.utils._get_changed_test_targets", return_value=None),
        patch("sase.ace.hooks.defaults.get_vcs_provider_config", return_value={}),
    ):
        result = get_initial_hooks_for_changespec()

    assert len(result) == 0


def test_get_initial_hooks_for_changespec_preserves_order() -> None:
    """Test that hooks are in correct order: required first, then test targets."""
    config = {"default_hooks": ["!$sase_google_presubmit", "$sase_google_lint"]}
    with (
        patch(
            "sase.workflows.utils._get_changed_test_targets", return_value="//foo:test1"
        ),
        patch("sase.ace.hooks.defaults.get_vcs_provider_config", return_value=config),
    ):
        result = get_initial_hooks_for_changespec()

    # Required hooks should be first
    assert result[0] == "!$sase_google_presubmit"
    assert result[1] == "$sase_google_lint"
    # Test targets should be last
    assert result[2] == "bb_rabbit_test //foo:test1"


# Tests for get_project_file_path
# Tests for get_cl_name_from_branch
@patch("sase.workflows.utils.get_vcs_provider")
def test_get_cl_name_from_branch_failure(mock_get_provider: MagicMock) -> None:
    """Test get_cl_name_from_branch returns None on failure."""
    mock_provider = MagicMock()
    mock_provider.get_branch_name.return_value = (False, None)
    mock_get_provider.return_value = mock_provider

    result = get_cl_name_from_branch()

    assert result is None


@patch("sase.workflows.utils.get_vcs_provider")
def test_get_cl_name_from_branch_empty(mock_get_provider: MagicMock) -> None:
    """Test get_cl_name_from_branch returns None for empty output."""
    mock_provider = MagicMock()
    mock_provider.get_branch_name.return_value = (True, None)
    mock_get_provider.return_value = mock_provider

    result = get_cl_name_from_branch()

    assert result is None


# Tests for get_project_from_workspace
@patch("sase.workflows.utils.get_vcs_provider")
def test_get_project_from_workspace_failure(mock_get_provider: MagicMock) -> None:
    """Test get_project_from_workspace returns None on failure."""
    mock_provider = MagicMock()
    mock_provider.get_workspace_name.return_value = (False, None)
    mock_get_provider.return_value = mock_provider

    result = get_project_from_workspace()

    assert result is None


@patch("sase.workflows.utils.get_vcs_provider")
def test_get_project_from_workspace_empty(mock_get_provider: MagicMock) -> None:
    """Test get_project_from_workspace returns None for empty output."""
    mock_provider = MagicMock()
    mock_provider.get_workspace_name.return_value = (True, "")
    mock_get_provider.return_value = mock_provider

    result = get_project_from_workspace()

    assert result is None


# Tests for get_changespec_from_file
def test_get_changespec_from_file_not_found() -> None:
    """Test get_changespec_from_file returns None when CL not found."""
    content = """NAME: other_feature
DESCRIPTION: Test description
STATUS: Ready
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write(content)
        temp_path = f.name

    try:
        result = get_changespec_from_file(temp_path, "nonexistent")
        assert result is None
    finally:
        Path(temp_path).unlink()
