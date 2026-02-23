"""Tests for ace/display_helpers.py."""

from dataclasses import dataclass

from sase.ace.display_helpers import (
    format_profile_with_count,
    format_running_claims_aligned,
)


@dataclass
class _MockWorkspaceClaim:
    """Mock workspace claim for testing."""

    workspace_num: int
    pid: int
    workflow: str
    cl_name: str | None


def test_format_running_claims_aligned_empty() -> None:
    """Test formatting empty claims list."""
    result = format_running_claims_aligned([])
    assert result == []


def test_format_running_claims_aligned_single_no_cl_name() -> None:
    """Test formatting single claim with no cl_name."""
    claims = [_MockWorkspaceClaim(5, 99999, "run", None)]
    result = format_running_claims_aligned(claims)
    assert len(result) == 1
    ws_col, pid_col, wf_col, cl_name = result[0]
    assert ws_col == "#5"
    assert pid_col == "99999"
    assert wf_col == "run"
    assert cl_name is None


# Tests for format_profile_with_count


@dataclass
class _MockMentorStatusLine:
    """Mock mentor status line for testing."""

    profile_name: str
    mentor_name: str = "mock_mentor"


def test_format_profile_with_count_no_status_lines() -> None:
    """Test formatting profile with no status lines (0 started)."""
    # Profile won't be found in config (test environment), fallback to name
    result = format_profile_with_count("test_profile", None)
    assert "test_profile" in result


# Tests for get_status_color
# Tests for is_suffix_timestamp
# Tests for is_entry_ref_suffix
