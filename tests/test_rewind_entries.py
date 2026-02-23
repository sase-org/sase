"""Tests for rewind_commit_entries function in rewind_workflow.renumber module."""

import os
import tempfile

from sase.rewind_workflow.renumber import rewind_commit_entries


def test_rewind_with_existing_proposals() -> None:
    """Test rewinding when there are existing proposals for the selected entry."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1) First commit\n")
        f.write("  (2) Second commit\n")
        f.write("  (2a) Proposal A for second\n")
        f.write("  (2b) Proposal B for second\n")
        f.write("  (3) Third commit\n")
        f.write("  (4) Fourth commit\n")
        temp_path = f.name

    try:
        result = rewind_commit_entries(temp_path, "test_cl", 2)
        assert result is True

        with open(temp_path) as f:
            content = f.read()

        # Entry (1) unchanged
        assert "(1) First commit" in content
        # Entry (2) stays as (2) with NEW PROPOSAL suffix
        assert "(2) Second commit - (!: NEW PROPOSAL)" in content
        # Existing proposals (2a), (2b) unchanged
        assert "(2a) Proposal A for second" in content
        assert "(2b) Proposal B for second" in content
        # Entry (3) becomes the lowest available letter (2c) with NEW PROPOSAL suffix
        assert "(2c) Third commit - (!: NEW PROPOSAL)" in content
        # Entry (4) deleted
        assert "(4) Fourth commit" not in content
    finally:
        os.unlink(temp_path)


def test_rewind_updates_mentors() -> None:
    """Test that MENTORS section is updated with correct ID mapping."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1) First commit\n")
        f.write("  (2) Second commit\n")
        f.write("  (3) Third commit\n")
        f.write("MENTORS:\n")
        f.write("  (2) mentor1\n")
        f.write("      | (2) [251224_120100] PASSED\n")
        f.write("  (3) mentor2\n")
        f.write("      | (3) [251224_120200] PASSED\n")
        temp_path = f.name

    try:
        result = rewind_commit_entries(temp_path, "test_cl", 2)
        assert result is True

        with open(temp_path) as f:
            content = f.read()

        # Mentor for (2) unchanged (stays as 2)
        assert "(2) mentor1" in content
        # Mentor for (3) becomes (2a)
        assert "(2a) mentor2" in content
    finally:
        os.unlink(temp_path)


def test_rewind_deletes_entries_after_entry_after() -> None:
    """Test that entries N+2, N+3, etc. are deleted."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1) First commit\n")
        f.write("  (2) Second commit\n")
        f.write("  (3) Third commit\n")
        f.write("  (4) Fourth commit\n")
        f.write("  (5) Fifth commit\n")
        f.write("  (6) Sixth commit\n")
        f.write("HOOKS:\n")
        f.write("  make lint\n")
        f.write("      | (4) [251224_120300] PASSED (4m)\n")
        f.write("      | (5) [251224_120400] PASSED (5m)\n")
        f.write("      | (6) [251224_120500] PASSED (6m)\n")
        temp_path = f.name

    try:
        result = rewind_commit_entries(temp_path, "test_cl", 3)
        assert result is True

        with open(temp_path) as f:
            content = f.read()

        # Entry (3) stays as (3) with NEW PROPOSAL suffix
        assert "(3) Third commit - (!: NEW PROPOSAL)" in content
        # Entry (4) becomes (3a) with NEW PROPOSAL suffix
        assert "(3a) Fourth commit - (!: NEW PROPOSAL)" in content
        # Entries (5), (6) deleted
        assert "(5) Fifth commit" not in content
        assert "(6) Sixth commit" not in content
        # Hook status for deleted entries should also be deleted
        assert "[251224_120400]" not in content
        assert "[251224_120500]" not in content
    finally:
        os.unlink(temp_path)


def test_rewind_nonexistent_file() -> None:
    """Test that rewinding a non-existent file returns False."""
    result = rewind_commit_entries("/nonexistent/file.gp", "test_cl", 1)
    assert result is False


def test_rewind_no_commits_section() -> None:
    """Test that rewinding when no COMMITS section exists returns False."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        temp_path = f.name

    try:
        result = rewind_commit_entries(temp_path, "test_cl", 1)
        assert result is False
    finally:
        os.unlink(temp_path)


def test_rewind_no_entry_after() -> None:
    """Test that rewinding fails when there's no entry after the selected one."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1) First commit\n")
        f.write("  (2) Second commit\n")
        temp_path = f.name

    try:
        # Try to rewind to (2) - no entry (3) exists
        result = rewind_commit_entries(temp_path, "test_cl", 2)
        assert result is False
    finally:
        os.unlink(temp_path)


def test_rewind_deletes_orphaned_mentors_entries() -> None:
    """Test that MENTORS entries for non-existent commits are deleted."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gp", delete=False) as f:
        f.write("NAME: test_cl\n")
        f.write("STATUS: Ready\n")
        f.write("COMMITS:\n")
        f.write("  (1) First commit\n")
        f.write("  (2) Second commit\n")
        f.write("  (3) Third commit\n")
        # Note: No (4) in COMMITS - MENTORS (4) is orphaned
        f.write("MENTORS:\n")
        f.write("  (1) mentor1\n")
        f.write("      | (1) [251224_120100] PASSED\n")
        f.write("  (4) mentor4\n")
        f.write("      | (4) [251224_120400] PASSED\n")
        temp_path = f.name

    try:
        result = rewind_commit_entries(temp_path, "test_cl", 2)
        assert result is True

        with open(temp_path) as f:
            content = f.read()

        # MENTORS (1) should remain
        assert "(1) mentor1" in content
        # MENTORS (4) should be deleted (orphaned entry > selected)
        assert "(4) mentor4" not in content
        assert "[251224_120400]" not in content
    finally:
        os.unlink(temp_path)
