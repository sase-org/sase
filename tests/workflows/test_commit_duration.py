"""Tests for timestamp/duration formatting and proposal rejection."""

import os
import tempfile
from datetime import datetime, timedelta
from sase.sase_utils import get_timezone

from sase.workflows.commit_utils import (
    add_commit_entry,
    reject_all_new_proposals,
)
from sase.workflows.commit_utils.entries import (
    _extract_timestamp_from_chat_path,
    format_chat_line_with_duration,
)


# Tests for _extract_timestamp_from_chat_path
def test_extract_timestamp_from_chat_path_invalid_timestamp() -> None:
    """Test that None is returned for invalid timestamp format."""
    # Missing underscore
    assert (
        _extract_timestamp_from_chat_path("~/.sase/chats/test-2512271430521.md") is None
    )
    # Non-digit characters
    assert (
        _extract_timestamp_from_chat_path("~/.sase/chats/test-25122a_143052.md") is None
    )


# Tests for format_chat_line_with_duration
def testformat_chat_line_with_duration_no_extension() -> None:
    """Test that paths without .md extension produce lines without duration."""
    path = "~/.sase/chats/test.txt"
    result = format_chat_line_with_duration(path)
    assert result == "      | CHAT: ~/.sase/chats/test.txt\n"


# Tests for add_commit_entry with duration suffix
def test_add_commit_entry_with_chat_duration() -> None:
    """Test that add_commit_entry includes duration suffix for chat path."""
    # Create a chat path with a recent timestamp
    eastern = get_timezone()
    past_time = datetime.now(eastern) - timedelta(minutes=2)
    past_timestamp = past_time.strftime("%y%m%d_%H%M%S")
    chat_path = f"~/.sase/chats/test-run-{past_timestamp}.md"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        temp_path = f.name

    try:
        result = add_commit_entry(
            project_file=temp_path,
            cl_name="test_cl",
            note="Test commit",
            chat_path=chat_path,
        )
        assert result is True

        with open(temp_path) as f:
            content = f.read()

        # Should have CHAT line with duration
        assert f"| CHAT: {chat_path}" in content
        assert "(" in content and ")" in content
        # Check for duration format (should be around 2m)
        assert "m" in content or "s" in content
    finally:
        os.unlink(temp_path)


def test_format_chat_line_with_end_timestamp_exact() -> None:
    """Test end_timestamp calculates exact duration regardless of current time."""
    # These timestamps are fixed, so the result should be deterministic
    start_timestamp = "250615_143052"  # June 15, 2025, 14:30:52
    end_timestamp = "250615_145052"  # June 15, 2025, 14:50:52 (20 min later)

    path = f"~/.sase/chats/test-run-{start_timestamp}.md"
    result = format_chat_line_with_duration(path, end_timestamp=end_timestamp)

    # Duration should be exactly 20 minutes
    assert "(20m0s)" in result or "(20m)" in result


# Tests for reject_all_new_proposals
def test_reject_all_new_proposals_success() -> None:
    """Test rejecting all new proposals changes suffix from (!:) to (~!:)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1) Initial commit\n")
        f.write("  (1a) Proposal one - (!: NEW PROPOSAL)\n")
        f.write("  (1b) Proposal two - (!: NEW PROPOSAL)\n")
        temp_path = f.name

    try:
        result = reject_all_new_proposals(temp_path, "test_cl")
        assert result == 2

        # Verify the file was updated
        with open(temp_path, encoding="utf-8") as f:
            content = f.read()
        assert "(~!: NEW PROPOSAL)" in content
        assert "(!: NEW PROPOSAL)" not in content
    finally:
        os.unlink(temp_path)


def test_reject_all_new_proposals_wrong_cl_name() -> None:
    """Test that returning 0 when CL name doesn't match."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1a) Proposal - (!: NEW PROPOSAL)\n")
        temp_path = f.name

    try:
        result = reject_all_new_proposals(temp_path, "wrong_cl")
        assert result == 0
    finally:
        os.unlink(temp_path)
