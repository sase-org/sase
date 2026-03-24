"""Tests for commit_workflow.changespec_queries module."""

from unittest.mock import MagicMock, patch

from sase.workflows.commit.changespec_queries import changespec_exists


# === Tests for changespec_exists ===


@patch("sase.workflows.commit.changespec_queries.get_project_file_path")
@patch("builtins.open")
def test_changespec_exists_exception(
    mock_open: MagicMock, mock_get_path: MagicMock
) -> None:
    """Test changespec_exists returns False on exception."""
    mock_get_path.return_value = "/some/path.gp"
    mock_open.side_effect = PermissionError("Access denied")

    with patch("os.path.isfile", return_value=True):
        result = changespec_exists("test_project", "test_cl")
        assert result is False
