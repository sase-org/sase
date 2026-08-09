"""Tests for ace.operations module."""

import tempfile
from unittest.mock import MagicMock, patch

from sase.ace.operations import (
    get_available_workflows,
    get_workspace_directory,
    update_to_changespec as update_to_patch,  # legacy ACE API name
)

# === Tests for get_workspace_directory ===


@patch("sase.ace.operations.get_workspace_directory_for_num")
@patch("sase.ace.operations.get_first_available_workspace")
def test_get_workspace_directory_main_workspace(
    mock_get_first: MagicMock, mock_get_dir: MagicMock
) -> None:
    """Test get_workspace_directory returns None suffix for main workspace."""
    mock_get_first.return_value = 1
    mock_get_dir.return_value = ("/path/to/main", None)

    mock_patch = MagicMock()
    mock_patch.file_path = "/project.sase"
    mock_patch.project_basename = "project"

    result = get_workspace_directory(mock_patch)

    assert result == ("/path/to/main", None)


# === Tests for _has_failing_hooks_for_fix ===


# === Tests for get_available_workflows ===


@patch("sase.ace.operations._has_failing_hooks_for_fix")
def test_get_available_workflows_crs_with_suffix_ignored(
    mock_has_failing: MagicMock,
) -> None:
    """Test critique comment with suffix is not included in workflows."""
    mock_has_failing.return_value = False

    mock_comment = MagicMock()
    mock_comment.reviewer = "critique"
    mock_comment.suffix = "timestamp_123"

    mock_patch = MagicMock()
    mock_patch.comments = [mock_comment]

    result = get_available_workflows(mock_patch)

    assert result == []


# === Tests for update_to_patch ===


@patch("sase.ace.operations.get_workspace_dir_from_project")
def test_update_to_patch_workspace_not_found(
    mock_get_dir: MagicMock,
) -> None:
    """Test update_to_patch handles workspace lookup failure."""
    mock_get_dir.side_effect = RuntimeError("Workspace not found")

    mock_patch = MagicMock()
    mock_patch.project_basename = "test_project"

    success, error = update_to_patch(mock_patch)

    assert success is False
    assert error == "Workspace not found"


def test_update_to_patch_directory_not_exists() -> None:
    """Test update_to_patch handles non-existent directory."""
    mock_patch = MagicMock()

    success, error = update_to_patch(mock_patch, workspace_dir="/nonexistent/path")

    assert success is False
    assert error is not None
    assert "does not exist" in error


def test_update_to_patch_path_not_directory() -> None:
    """Test update_to_patch handles path that is not a directory."""
    with tempfile.NamedTemporaryFile() as tmp_file:
        mock_patch = MagicMock()

        success, error = update_to_patch(mock_patch, workspace_dir=tmp_file.name)

        assert success is False
        assert error is not None
        assert "not a directory" in error


@patch("sase.vcs_provider.get_vcs_provider")
def test_update_to_patch_uses_parent_revision(
    mock_get_provider: MagicMock,
) -> None:
    """Test update_to_patch uses parent when no revision specified."""
    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.resolve_revision.side_effect = lambda name, *_: name
    mock_get_provider.return_value = mock_provider

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_patch = MagicMock()
        mock_patch.parent = "parent_rev"

        success, error = update_to_patch(mock_patch, workspace_dir=tmpdir)

        assert success is True
        mock_provider.checkout.assert_called_once_with("parent_rev", tmpdir)


@patch("sase.vcs_provider.get_vcs_provider")
def test_update_to_patch_uses_provider_default(
    mock_get_provider: MagicMock,
) -> None:
    """Test update_to_patch uses provider default when no parent or revision."""
    mock_provider = MagicMock()
    mock_provider.checkout.return_value = (True, None)
    mock_provider.get_default_parent_revision.return_value = "p4head"
    mock_provider.resolve_revision.side_effect = lambda name, *_: name
    mock_get_provider.return_value = mock_provider

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_patch = MagicMock()
        mock_patch.parent = None

        success, error = update_to_patch(mock_patch, workspace_dir=tmpdir)

        assert success is True
        mock_provider.get_default_parent_revision.assert_called_once_with(tmpdir)
        mock_provider.checkout.assert_called_once_with("p4head", tmpdir)
