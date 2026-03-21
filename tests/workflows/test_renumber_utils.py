"""Tests for renumber_utils shared module."""

from sase.workflows.renumber_utils import (
    find_commits_section,
    parse_commit_entries,
)

# Tests for sort_hook_status_lines


# Tests for build_commits_section


# Tests for sort_entries_by_id


# Tests for parse_commit_entries


def test_parse_commit_entries_with_metadata() -> None:
    """Test parsing commit entries with CHAT and DIFF lines."""
    commit_lines = [
        "  (1) First commit\n",
        "      | CHAT: /path/to/chat\n",
        "      | DIFF: /path/to/diff\n",
    ]

    result = parse_commit_entries(commit_lines)

    assert len(result) == 1
    assert result[0]["chat"] == "/path/to/chat"
    assert result[0]["diff"] == "/path/to/diff"


# Tests for find_commits_section


def test_find_commits_section_not_found() -> None:
    """Test finding commits section when CL not found."""
    lines = [
        "NAME: other_cl\n",
        "STATUS: Ready\n",
        "COMMITS:\n",
        "  (1) First commit\n",
    ]

    start, end = find_commits_section(lines, "test_cl")

    assert start == -1
    assert end == -1
