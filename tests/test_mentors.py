"""Tests for the mentors module - MENTORS field operations."""

import tempfile
from pathlib import Path

from sase.ace.changespec import MentorEntry, MentorStatusLine
from sase.ace.mentors import (
    add_mentor_entry,
    format_mentors_field,
    set_mentor_status,
)


def testformat_mentors_field_empty() -> None:
    """Test formatting empty mentors list."""
    lines = format_mentors_field([])
    assert lines == []


def testformat_mentors_field_running_no_timestamp_prefix() -> None:
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
    lines = format_mentors_field([entry])
    content = "".join(lines)

    # RUNNING line should NOT have timestamp prefix
    assert "| feature:complete - RUNNING" in content
    assert "[260107_141615] feature:complete" not in content

    # PASSED line SHOULD have timestamp prefix
    assert "[260107_140027] feature:soundness - PASSED" in content


def testformat_mentors_field_with_error_suffix() -> None:
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
    lines = format_mentors_field([entry])
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


def test_add_mentor_entry_last_changespec_with_trailing_blanks() -> None:
    """Test MENTORS is inside ChangeSpec boundary when trailing blank lines exist.

    When the target is the last ChangeSpec and the file has trailing blank lines
    (2+ blank lines = end-of-ChangeSpec boundary), MENTORS must be inserted
    BEFORE those blanks so the parser includes it in the ChangeSpec.
    """
    from sase.ace.changespec.parser import parse_project_file

    content = "NAME: test-cl\nSTATUS: Ready\nDESCRIPTION:\n  Test description\n\n\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write(content)
        file_path = f.name

    result = add_mentor_entry(file_path, "test-cl", "1", ["feature"])
    assert result is True

    # Parse and verify the MENTORS field is visible to the parser
    changespecs = parse_project_file(file_path)
    assert len(changespecs) == 1
    assert changespecs[0].mentors is not None
    assert len(changespecs[0].mentors) == 1
    assert changespecs[0].mentors[0].entry_id == "1"
    assert changespecs[0].mentors[0].profiles == ["feature"]

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


def testformat_mentors_field_commented_shows_timestamp_prefix() -> None:
    """Test that COMMENTED status lines show timestamp prefix like PASSED."""
    entry = MentorEntry(
        entry_id="1",
        profiles=["code"],
        status_lines=[
            MentorStatusLine(
                timestamp="260321_120000",
                profile_name="code",
                mentor_name="quality",
                status="COMMENTED",
                duration="3m15s",
            ),
        ],
    )
    lines = format_mentors_field([entry])
    content = "".join(lines)

    # COMMENTED should show timestamp prefix (like PASSED)
    assert "[260321_120000] code:quality - COMMENTED" in content
    assert "3m15s" in content


def test_set_mentor_status_commented() -> None:
    """Test setting COMMENTED status."""
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
        status="COMMENTED",
        duration="2m30s",
    )

    assert result is True

    with open(file_path) as f:
        updated_content = f.read()

    assert "COMMENTED" in updated_content
    assert "2m30s" in updated_content

    Path(file_path).unlink()


def test_merge_preserves_commented_status_from_disk() -> None:
    """Test that merge preserves disk's COMMENTED status over stale RUNNING."""
    from sase.ace.mentors import merge_mentor_status_lines

    disk_mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["code"],
            status_lines=[
                MentorStatusLine(
                    profile_name="code",
                    mentor_name="quality",
                    status="COMMENTED",
                    timestamp="260321_120000",
                    duration="3m15s",
                ),
            ],
        )
    ]

    caller_mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["code"],
            status_lines=[
                MentorStatusLine(
                    profile_name="code",
                    mentor_name="quality",
                    status="RUNNING",
                    timestamp="260321_120000",
                    suffix="mentor_quality-12345-260321_120000",
                    suffix_type="running_agent",
                ),
            ],
        )
    ]

    result = merge_mentor_status_lines(disk_mentors, caller_mentors)

    assert result[0].status_lines is not None
    sl = result[0].status_lines[0]
    assert sl.status == "COMMENTED"
    assert sl.duration == "3m15s"


def testformat_mentors_field_with_plain_suffix() -> None:
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
    lines = format_mentors_field([entry])
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


def test_merge_preserves_terminal_status_from_disk() -> None:
    """Test that merge_mentor_status_lines preserves terminal disk status.

    When the caller has a stale RUNNING status but the disk has been updated
    to PASSED by set_mentor_status(), the merge should prefer the disk version.
    This prevents the race condition where update_changespec_mentors_field()
    overwrites a newer terminal status with a stale RUNNING status.
    """
    from sase.ace.mentors import merge_mentor_status_lines

    # Disk has PASSED (updated by set_mentor_status after caller's read)
    disk_mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["code"],
            status_lines=[
                MentorStatusLine(
                    profile_name="code",
                    mentor_name="quality",
                    status="PASSED",
                    timestamp="260306_093014",
                    duration="5m30s",
                ),
            ],
        )
    ]

    # Caller has stale RUNNING (read before set_mentor_status ran)
    caller_mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["code"],
            status_lines=[
                MentorStatusLine(
                    profile_name="code",
                    mentor_name="quality",
                    status="RUNNING",
                    timestamp="260306_093014",
                    suffix="mentor_quality-12345-260306_093014",
                    suffix_type="running_agent",
                ),
            ],
        )
    ]

    result = merge_mentor_status_lines(disk_mentors, caller_mentors)

    # The disk's PASSED status should win over the caller's stale RUNNING
    assert result[0].status_lines is not None
    sl = result[0].status_lines[0]
    assert sl.status == "PASSED"
    assert sl.duration == "5m30s"
    assert sl.suffix_type is None  # PASSED has no running_agent suffix


def test_merge_preserves_caller_killed_agent() -> None:
    """Test that merge preserves caller's killed_agent over disk's RUNNING.

    When the caller intentionally marks a mentor as killed_agent (e.g.,
    mark_mentor_agents_as_killed), the caller's version should win over
    the disk's RUNNING status.
    """
    from sase.ace.mentors import merge_mentor_status_lines

    # Disk still has RUNNING (process was just killed, hasn't updated yet)
    disk_mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["code"],
            status_lines=[
                MentorStatusLine(
                    profile_name="code",
                    mentor_name="quality",
                    status="RUNNING",
                    timestamp="260306_093014",
                    suffix="mentor_quality-12345-260306_093014",
                    suffix_type="running_agent",
                ),
            ],
        )
    ]

    # Caller has killed_agent (set by mark_mentor_agents_as_killed)
    caller_mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["code"],
            status_lines=[
                MentorStatusLine(
                    profile_name="code",
                    mentor_name="quality",
                    status="RUNNING",
                    timestamp="260306_093014",
                    suffix="mentor_quality-12345-260306_093014",
                    suffix_type="killed_agent",
                ),
            ],
        )
    ]

    result = merge_mentor_status_lines(disk_mentors, caller_mentors)

    # Caller's killed_agent should be preserved (disk is non-terminal)
    assert result[0].status_lines is not None
    sl = result[0].status_lines[0]
    assert sl.suffix_type == "killed_agent"


def test_merge_adds_missing_status_lines() -> None:
    """Test that merge still adds status lines the caller doesn't have."""
    from sase.ace.mentors import merge_mentor_status_lines

    # Disk has two status lines
    disk_mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["code"],
            status_lines=[
                MentorStatusLine(
                    profile_name="code",
                    mentor_name="quality",
                    status="RUNNING",
                    timestamp="260306_093014",
                ),
                MentorStatusLine(
                    profile_name="code",
                    mentor_name="tests",
                    status="PASSED",
                    timestamp="260306_093016",
                    duration="3m",
                ),
            ],
        )
    ]

    # Caller only has one (the other was added after caller's read)
    caller_mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["code"],
            status_lines=[
                MentorStatusLine(
                    profile_name="code",
                    mentor_name="quality",
                    status="RUNNING",
                    timestamp="260306_093014",
                ),
            ],
        )
    ]

    result = merge_mentor_status_lines(disk_mentors, caller_mentors)

    # Should now have both status lines
    assert result[0].status_lines is not None
    assert len(result[0].status_lines) == 2
    names = {sl.mentor_name for sl in result[0].status_lines}
    assert names == {"quality", "tests"}


# Tests for clear_mentor_draft_flags
