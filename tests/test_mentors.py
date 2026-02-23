"""Tests for the mentors module - MENTORS field operations."""

import tempfile
from pathlib import Path

from sase.ace.changespec import MentorEntry, MentorStatusLine
from sase.ace.mentors import (
    _format_mentors_field,
    add_mentor_entry,
    set_mentor_status,
)


def test_format_mentors_field_empty() -> None:
    """Test formatting empty mentors list."""
    lines = _format_mentors_field([])
    assert lines == []


def test_format_mentors_field_running_no_timestamp_prefix() -> None:
    """Test that RUNNING status lines don't show timestamp prefix.

    The timestamp is stored in the model but should not be displayed
    for RUNNING mentors - only for PASSED/FAILED.
    """
    entry = MentorEntry(
        entry_id="1",
        profiles=["feature"],
        status_lines=[
            MentorStatusLine(
                timestamp="260107_141615",
                profile_name="feature",
                mentor_name="complete",
                status="RUNNING",
                suffix="mentor_complete-12345-260107_141615",
                suffix_type="running_agent",
            ),
            MentorStatusLine(
                timestamp="260107_140027",
                profile_name="feature",
                mentor_name="soundness",
                status="PASSED",
                duration="5m30s",
            ),
        ],
    )
    lines = _format_mentors_field([entry])
    content = "".join(lines)

    # RUNNING line should NOT have timestamp prefix
    assert "| feature:complete - RUNNING" in content
    assert "[260107_141615] feature:complete" not in content

    # PASSED line SHOULD have timestamp prefix
    assert "[260107_140027] feature:soundness - PASSED" in content


def test_format_mentors_field_with_error_suffix() -> None:
    """Test formatting with error suffix."""
    entry = MentorEntry(
        entry_id="1",
        profiles=["test"],
        status_lines=[
            MentorStatusLine(
                timestamp="251231_120000",
                profile_name="test",
                mentor_name="complete",
                status="FAILED",
                suffix="Connection error",
                suffix_type="error",
            ),
        ],
    )
    lines = _format_mentors_field([entry])
    # Should contain error marker
    assert any("!:" in line for line in lines)


def test_add_mentor_entry_new() -> None:
    """Test adding a new mentor entry to a file."""
    content = """NAME: test-cl
STATUS: Ready
DESCRIPTION:
  Test description
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    result = add_mentor_entry(file_path, "test-cl", "1", ["feature"])

    assert result is True

    # Read and verify
    with open(file_path) as f:
        updated_content = f.read()

    assert "MENTORS:" in updated_content
    assert "(1) feature" in updated_content

    Path(file_path).unlink()


def test_add_mentor_entry_merge_profiles() -> None:
    """Test adding profiles to existing mentor entry."""
    content = """NAME: test-cl
STATUS: Ready
MENTORS:
  (1) feature
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    result = add_mentor_entry(file_path, "test-cl", "1", ["tests"])

    assert result is True

    # Read and verify profiles are merged
    with open(file_path) as f:
        updated_content = f.read()

    # Should have both profiles
    assert "feature" in updated_content
    assert "tests" in updated_content

    Path(file_path).unlink()


def test_set_mentor_status_update_existing() -> None:
    """Test updating existing mentor status."""
    content = """NAME: test-cl
STATUS: Ready
MENTORS:
  (1) feature
      | feature:complete - RUNNING - (@: mentor_complete-123)
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    result = set_mentor_status(
        file_path,
        "test-cl",
        "1",
        "feature",
        "complete",
        status="PASSED",
        duration="1h2m3s",
    )

    assert result is True

    with open(file_path) as f:
        updated_content = f.read()

    assert "PASSED" in updated_content
    assert "1h2m3s" in updated_content

    Path(file_path).unlink()


def test_format_mentors_field_with_plain_suffix() -> None:
    """Test formatting with plain suffix (no type)."""
    entry = MentorEntry(
        entry_id="1",
        profiles=["test"],
        status_lines=[
            MentorStatusLine(
                timestamp="251231_120000",
                profile_name="test",
                mentor_name="complete",
                status="PASSED",
                suffix="some_suffix",
                suffix_type=None,  # Plain suffix
            ),
        ],
    )
    lines = _format_mentors_field([entry])
    content = "".join(lines)
    assert "some_suffix" in content


def test_set_mentor_status_creates_entry_if_missing() -> None:
    """Test that set_mentor_status creates entry if it doesn't exist."""
    content = """NAME: test-cl
STATUS: Ready
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    result = set_mentor_status(
        file_path,
        "test-cl",
        "1",
        "feature",
        "complete",
        status="RUNNING",
    )

    assert result is True

    with open(file_path) as f:
        updated_content = f.read()

    assert "MENTORS:" in updated_content
    assert "feature:complete" in updated_content
    assert "RUNNING" in updated_content

    Path(file_path).unlink()


# Tests for clear_mentor_draft_flags
