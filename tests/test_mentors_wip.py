"""Tests for the mentors module - Draft-related functionality."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.ace.changespec import MentorEntry, MentorStatusLine
from sase.ace.mentors import (
    _format_mentors_field,
    _format_profile_with_count,
    clear_mentor_draft_flags,
    set_mentor_draft_flags,
)
from sase.mentor_config import MentorConfig, MentorProfileConfig

# Tests for Draft filtering


def test_format_profile_with_count_wip_filters_started() -> None:
    """Test that is_draft=True only counts started mentors with run_on_draft."""
    # Mock a profile with 3 mentors, only 1 has run_on_draft=True
    mock_profile = MentorProfileConfig(
        profile_name="test_profile",
        mentors=[
            MentorConfig(mentor_name="quick", prompt="p1", run_on_draft=True),
            MentorConfig(mentor_name="full", prompt="p2", run_on_draft=False),
            MentorConfig(mentor_name="detailed", prompt="p3", run_on_draft=False),
        ],
        file_globs=["*.py"],
    )

    def mock_get_profile(name: str) -> MentorProfileConfig | None:
        if name == "test_profile":
            return mock_profile
        return None

    # Status lines for 2 mentors (1 with run_on_draft, 1 without)
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
        "sase.mentor_config.get_mentor_profile_by_name",
        side_effect=mock_get_profile,
    ):
        # Without WIP: should count both started mentors (2/3)
        result_normal = _format_profile_with_count(
            "test_profile", status_lines, is_draft=False
        )
        assert result_normal == "test_profile[2/3]"

        # With WIP: should only count the run_on_draft mentor (1/1)
        result_wip = _format_profile_with_count(
            "test_profile", status_lines, is_draft=True
        )
        assert result_wip == "test_profile[1/1]"


def test_format_mentors_field_non_wip_shows_all_profiles() -> None:
    """Test that non-WIP entries show all profiles regardless of run_on_draft."""
    # Profile A has run_on_draft mentors, Profile B does not
    profiles = {
        "profile_a": MentorProfileConfig(
            profile_name="profile_a",
            mentors=[MentorConfig(mentor_name="m1", prompt="p1", run_on_draft=True)],
            file_globs=["*.py"],
        ),
        "profile_b": MentorProfileConfig(
            profile_name="profile_b",
            mentors=[MentorConfig(mentor_name="m2", prompt="p2", run_on_draft=False)],
            file_globs=["*.js"],
        ),
    }

    def mock_get_profile(name: str) -> MentorProfileConfig | None:
        return profiles.get(name)

    entry = MentorEntry(
        entry_id="1",
        profiles=["profile_a", "profile_b"],
        status_lines=None,
        is_draft=False,  # Not WIP
    )

    with patch(
        "sase.mentor_config.get_mentor_profile_by_name",
        side_effect=mock_get_profile,
    ):
        lines = _format_mentors_field([entry])
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

    # Mock profile functions to allow any profile
    with patch("sase.mentor_config.profile_has_draft_mentors", return_value=True):
        with patch("sase.mentor_config.get_mentor_profile_by_name", return_value=None):
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

    with patch("sase.mentor_config.get_mentor_profile_by_name", return_value=None):
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

    with patch("sase.mentor_config.profile_has_draft_mentors", return_value=True):
        with patch("sase.mentor_config.get_mentor_profile_by_name", return_value=None):
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


def test_set_mentor_draft_flags_filters_profiles() -> None:
    """Test that set_mentor_draft_flags filters to only WIP-enabled profiles."""
    content = """NAME: test-cl
STATUS: Ready
MENTORS:
  (1) profile_a profile_b
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        file_path = f.name

    def mock_has_wip(name: str) -> bool:
        # profile_a has WIP mentors, profile_b does not
        return name == "profile_a"

    with patch(
        "sase.mentor_config.profile_has_draft_mentors", side_effect=mock_has_wip
    ):
        with patch("sase.mentor_config.get_mentor_profile_by_name", return_value=None):
            result = set_mentor_draft_flags(file_path, "test-cl")
            assert result is True

    with open(file_path) as file_obj:
        updated_content = file_obj.read()

    # Only profile_a should remain, profile_b should be filtered out
    assert "profile_a" in updated_content
    assert "profile_b" not in updated_content
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
