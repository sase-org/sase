"""Tests for the mentors module - Draft-related functionality."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.ace.changespec import MentorEntry, MentorStatusLine
from sase.ace.mentors import (
    clear_mentor_draft_flags,
    format_mentors_field,
    format_profile_with_count,
    set_mentor_draft_flags,
)
from sase.config.mentor import MentorProfileConfig
from test_utils import make_mentor_config


def testformat_profile_with_count_counts_all_mentors() -> None:
    """Test that format_profile_with_count counts all started mentors."""
    mock_profile = MentorProfileConfig(
        profile_name="test_profile",
        mentors=[
            make_mentor_config(mentor_name="quick"),
            make_mentor_config(mentor_name="full"),
            make_mentor_config(mentor_name="detailed"),
        ],
        file_globs=["*.py"],
    )

    def mock_get_profile(name: str) -> MentorProfileConfig | None:
        if name == "test_profile":
            return mock_profile
        return None

    status_lines = [
        MentorStatusLine(
            timestamp="251231_120000",
            profile_name="test_profile",
            mentor_name="quick",
            status="RUNNING",
        ),
        MentorStatusLine(
            timestamp="251231_120000",
            profile_name="test_profile",
            mentor_name="full",
            status="RUNNING",
        ),
    ]

    with patch(
        "sase.config.mentor.get_mentor_profile_by_name",
        side_effect=mock_get_profile,
    ):
        result = format_profile_with_count("test_profile", status_lines)
        assert result == "test_profile[2/3]"


def testformat_mentors_field_shows_all_profiles() -> None:
    """Test that entries show all profiles."""
    profiles = {
        "profile_a": MentorProfileConfig(
            profile_name="profile_a",
            mentors=[make_mentor_config(mentor_name="m1")],
            file_globs=["*.py"],
        ),
        "profile_b": MentorProfileConfig(
            profile_name="profile_b",
            mentors=[make_mentor_config(mentor_name="m2")],
            file_globs=["*.js"],
        ),
    }

    def mock_get_profile(name: str) -> MentorProfileConfig | None:
        return profiles.get(name)

    entry = MentorEntry(
        entry_id="1",
        profiles=["profile_a", "profile_b"],
        status_lines=None,
        is_draft=False,
    )

    with patch(
        "sase.config.mentor.get_mentor_profile_by_name",
        side_effect=mock_get_profile,
    ):
        lines = format_mentors_field([entry])
        content = "".join(lines)

        # Both profiles should be visible
        assert "profile_a" in content
        assert "profile_b" in content
        # No #Draft suffix
        assert "#Draft" not in content


# Tests for clear_mentor_draft_flags (was clear_mentor_wip_flags)


def test_clear_mentor_draft_flags_clears_last_only() -> None:
    """Test that only the highest entry_id WIP entry has #Draft cleared."""
    content = """NAME: test-cl
STATUS: Draft
COMMITS:
  (1) First commit
  (2) Second commit
  (3) Third commit
MENTORS:
  (1) feature #Draft
  (2) feature #Draft
  (3) feature #Draft
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    with patch("sase.config.mentor.get_mentor_profile_by_name", return_value=None):
        result = clear_mentor_draft_flags(file_path, "test-cl")
        assert result is True

    with open(file_path) as f:
        updated_content = f.read()

    # Only entry (3) should have #Draft cleared
    lines = updated_content.split("\n")
    mentors_section = [ln for ln in lines if ln.strip().startswith("(")]
    assert any("(1)" in ln and "#Draft" in ln for ln in mentors_section)
    assert any("(2)" in ln and "#Draft" in ln for ln in mentors_section)
    assert any("(3)" in ln and "#Draft" not in ln for ln in mentors_section)

    Path(file_path).unlink()


def test_clear_mentor_draft_flags_no_wip_entries() -> None:
    """Test that nothing changes when no WIP entries exist."""
    content = """NAME: test-cl
STATUS: Ready
MENTORS:
  (1) feature
  (2) tests
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    with patch("sase.config.mentor.get_mentor_profile_by_name", return_value=None):
        result = clear_mentor_draft_flags(file_path, "test-cl")
        assert result is True

    with open(file_path) as f:
        updated_content = f.read()

    # Should be unchanged (profiles preserved without counts)
    assert "(1) feature" in updated_content
    assert "(2) tests" in updated_content

    Path(file_path).unlink()


def test_clear_mentor_draft_flags_wrong_changespec() -> None:
    """Test that other ChangeSpecs are not affected."""
    content = """NAME: other-cl
STATUS: Draft
MENTORS:
  (1) feature #Draft

NAME: test-cl
STATUS: Draft
MENTORS:
  (1) feature #Draft
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    with patch("sase.config.mentor.get_mentor_profile_by_name", return_value=None):
        result = clear_mentor_draft_flags(file_path, "test-cl")
        assert result is True

    with open(file_path) as f:
        updated_content = f.read()

    # other-cl should still have #Draft
    # test-cl should have #Draft cleared
    # Split by NAME: to check each section
    other_cl_start = updated_content.find("NAME: other-cl")
    test_cl_start = updated_content.find("NAME: test-cl")
    other_cl_section = updated_content[other_cl_start:test_cl_start]
    test_cl_section = updated_content[test_cl_start:]

    assert "#Draft" in other_cl_section
    assert "#Draft" not in test_cl_section

    Path(file_path).unlink()


def test_clear_mentor_draft_flags_no_mentors() -> None:
    """Test that function returns True when no mentors exist."""
    content = """NAME: test-cl
STATUS: Ready
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    result = clear_mentor_draft_flags(file_path, "test-cl")
    assert result is True

    Path(file_path).unlink()


def test_clear_mentor_draft_flags_changespec_not_found() -> None:
    """Test that function returns True when changespec not found."""
    content = """NAME: other-cl
STATUS: Ready
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    result = clear_mentor_draft_flags(file_path, "nonexistent-cl")
    assert result is True

    Path(file_path).unlink()


# Tests for set_mentor_draft_flags (was set_mentor_wip_flags)


def test_set_mentor_draft_flags_keeps_all_profiles() -> None:
    """Test that set_mentor_draft_flags keeps all profiles (no filtering)."""
    content = """NAME: test-cl
STATUS: Ready
MENTORS:
  (1) profile_a profile_b
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    with patch("sase.config.mentor.get_mentor_profile_by_name", return_value=None):
        result = set_mentor_draft_flags(file_path, "test-cl")
        assert result is True

    with open(file_path) as file_obj:
        updated_content = file_obj.read()

    # Both profiles should remain
    assert "profile_a" in updated_content
    assert "profile_b" in updated_content
    assert "#Draft" in updated_content

    Path(file_path).unlink()


def test_set_mentor_draft_flags_no_mentors() -> None:
    """Test that function returns True when no mentors exist."""
    content = """NAME: test-cl
STATUS: Ready
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    result = set_mentor_draft_flags(file_path, "test-cl")
    assert result is True

    Path(file_path).unlink()


def test_set_mentor_draft_flags_changespec_not_found() -> None:
    """Test that function returns True when changespec not found."""
    content = """NAME: other-cl
STATUS: Ready
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    result = set_mentor_draft_flags(file_path, "nonexistent-cl")
    assert result is True

    Path(file_path).unlink()
