"""Tests for MentorConfig and MentorProfileConfig dataclass validation."""

import pytest
from sase.config.mentor import MentorFocusArea, MentorProfileConfig
from test_utils import make_mentor_config


def test_mentor_config_dataclass() -> None:
    """Test MentorConfig dataclass."""
    config = make_mentor_config(mentor_name="test", role="test reviewer")

    assert config.mentor_name == "test"
    assert config.role == "test reviewer"
    assert len(config.focus_areas) == 1


def test_mentor_config_focus_areas() -> None:
    """Test MentorConfig with explicit focus areas."""
    focus_areas = [
        MentorFocusArea(focus_name="comments", description="Check comments"),
        MentorFocusArea(focus_name="style", description="Check style"),
    ]
    config = make_mentor_config(
        mentor_name="quality",
        role="code quality expert",
        focus_areas=focus_areas,
    )
    assert len(config.focus_areas) == 2
    assert config.focus_areas[0].focus_name == "comments"
    assert config.focus_areas[1].description == "Check style"


def test_mentor_profile_config_no_criteria_raises_error() -> None:
    """Test MentorProfileConfig raises ValueError when no criteria provided."""
    mentors = [make_mentor_config(mentor_name="mentor1")]
    with pytest.raises(
        ValueError,
        match="must have at least one of: file_globs, diff_regexes, amend_note_regexes, or first_commit",
    ):
        MentorProfileConfig(
            profile_name="invalid_profile",
            mentors=mentors,
        )


def test_mentor_profile_config_first_commit_alone_is_valid() -> None:
    """Test MentorProfileConfig with only first_commit=True is valid."""
    mentors = [make_mentor_config(mentor_name="mentor1")]
    profile = MentorProfileConfig(
        profile_name="first_commit_profile",
        mentors=mentors,
        first_commit=True,
    )
    assert profile.first_commit is True
