"""Tests for commit_workflow.changespec_queries module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.workflows.commit.changespec_queries import (
    changespec_exists,
    get_blocking_exact_match_changespec,
)

# === Tests for project_file_exists ===


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


# === Tests for get_blocking_exact_match_changespec ===


@patch("sase.workflows.commit.changespec_queries.get_project_file_path")
def test_get_blocking_exact_match_no_file(mock_get_path: MagicMock) -> None:
    """Test returns None when project file doesn't exist."""
    mock_get_path.return_value = "/nonexistent/path.gp"
    result = get_blocking_exact_match_changespec("proj", "foo")
    assert result is None


@patch("sase.workflows.commit.changespec_queries.get_project_file_path")
@patch("sase.ace.changespec.parse_project_file")
def test_get_blocking_exact_match_mailed_status(
    mock_parse: MagicMock, mock_get_path: MagicMock
) -> None:
    """Test returns (name, 'Mailed') when exact match with Mailed status."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("# Project File\n")
        f.flush()
        mock_get_path.return_value = f.name

        mock_cs = MagicMock()
        mock_cs.name = "proj_bar"
        mock_cs.status = "Mailed"
        mock_parse.return_value = [mock_cs]

        result = get_blocking_exact_match_changespec("proj", "proj_bar")
        assert result == ("proj_bar", "Mailed")

        Path(f.name).unlink()


@patch("sase.workflows.commit.changespec_queries.get_project_file_path")
@patch("sase.ace.changespec.parse_project_file")
def test_get_blocking_exact_match_suffixed_not_blocking(
    mock_parse: MagicMock, mock_get_path: MagicMock
) -> None:
    """Test returns None when suffixed version exists but not exact match."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("# Project File\n")
        f.flush()
        mock_get_path.return_value = f.name

        # Only proj_foo__1 exists (suffixed), not proj_foo (exact)
        mock_cs = MagicMock()
        mock_cs.name = "proj_foo__1"
        mock_cs.status = "Ready"
        mock_parse.return_value = [mock_cs]

        result = get_blocking_exact_match_changespec("proj", "foo")
        assert result is None

        Path(f.name).unlink()
