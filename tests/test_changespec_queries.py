"""Tests for commit_workflow.patch_queries module."""

from unittest.mock import MagicMock, patch

from sase.workflows.commit.patch_queries import patch_exists


# === Tests for patch_exists ===


@patch("sase.workflows.commit.patch_queries.get_project_file_path")
@patch("builtins.open")
def test_patch_exists_exception(mock_open: MagicMock, mock_get_path: MagicMock) -> None:
    """Test patch_exists returns False on exception."""
    mock_get_path.return_value = "/some/path.sase"
    mock_open.side_effect = PermissionError("Access denied")

    with patch("os.path.isfile", return_value=True):
        result = patch_exists("test_project", "test_cl")
        assert result is False
