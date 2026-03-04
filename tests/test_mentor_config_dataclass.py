"""Tests for MentorConfig and MentorProfileConfig dataclass validation."""

import pytest
from sase.mentor_config import MentorConfig, MentorProfileConfig


def test_mentor_config_dataclass() -> None:
    """Test MentorConfig dataclass."""
    config = MentorConfig(mentor_name="test", prompt="test prompt")

    assert config.mentor_name == "test"
    assert config.prompt == "test prompt"


def test_mentor_profile_config_no_criteria_raises_error() -> None:
    """Test MentorProfileConfig raises ValueError when no criteria provided."""
    mentors = [MentorConfig(mentor_name="mentor1", prompt="Prompt 1")]
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
    mentors = [MentorConfig(mentor_name="mentor1", prompt="Prompt 1")]
    profile = MentorProfileConfig(
        profile_name="first_commit_profile",
        mentors=mentors,
        first_commit=True,
    )
    assert profile.first_commit is True
