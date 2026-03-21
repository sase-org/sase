"""Tests for commit_workflow/branch_info.py - branch and CL info retrieval."""

from unittest.mock import MagicMock, patch

from sase.workflows.commit.branch_info import get_parent_branch_name


# Tests for get_parent_branch_name
@patch("sase.workflows.commit.branch_info.get_vcs_provider")
def test_get_parent_branch_name_failure(mock_get_provider: MagicMock) -> None:
    """Test get_parent_branch_name when command fails."""
    mock_provider = MagicMock()
    mock_provider.get_branch_name.return_value = (False, "command failed")
    mock_get_provider.return_value = mock_provider

    result = get_parent_branch_name(cwd="/fake/dir")

    assert result is None


@patch("sase.workflows.commit.branch_info.get_vcs_provider")
def test_get_parent_branch_name_whitespace_only(mock_get_provider: MagicMock) -> None:
    """Test get_parent_branch_name with whitespace only output."""
    mock_provider = MagicMock()
    mock_provider.get_branch_name.return_value = (True, "   \n")
    mock_get_provider.return_value = mock_provider

    result = get_parent_branch_name(cwd="/fake/dir")

    assert result is None
