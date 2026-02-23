"""Tests for mentor profile and mentor retrieval functions, and WIP-related functions."""

from unittest.mock import patch

from sase.mentor_config import (
    MentorConfig,
    MentorProfileConfig,
    get_mentor_from_profile,
    profile_has_draft_mentors,
)
from test_utils import mentor_config_from_yaml


def test_get_mentor_from_profile_found() -> None:
    """Test getting a mentor from a profile when it exists."""
    mentors = [
        MentorConfig(mentor_name="mentor1", prompt="Prompt 1"),
        MentorConfig(mentor_name="mentor2", prompt="Prompt 2"),
        MentorConfig(mentor_name="mentor3", prompt="Prompt 3", run_on_draft=True),
    ]
    profile = MentorProfileConfig(
        profile_name="test_profile",
        mentors=mentors,
        file_globs=["*.py"],
    )

    mentor = get_mentor_from_profile(profile, "mentor2")

    assert mentor is not None
    assert mentor.mentor_name == "mentor2"
    assert mentor.prompt == "Prompt 2"
    assert mentor.run_on_draft is False


def test_get_mentor_from_profile_not_found() -> None:
    """Test getting a mentor from a profile when it doesn't exist."""
    mentors = [
        MentorConfig(mentor_name="mentor1", prompt="Prompt 1"),
        MentorConfig(mentor_name="mentor2", prompt="Prompt 2"),
    ]
    profile = MentorProfileConfig(
        profile_name="test_profile",
        mentors=mentors,
        file_globs=["*.py"],
    )

    mentor = get_mentor_from_profile(profile, "nonexistent")

    assert mentor is None


def test_profile_has_draft_mentors_false() -> None:
    """Test profile_has_draft_mentors returns False when no WIP mentors."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
    mentors:
      - mentor_name: full
        prompt: Full review.
      - mentor_name: detailed
        prompt: Detailed review.
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        result = profile_has_draft_mentors("test_profile")

    assert result is False


def test_profile_has_draft_mentors_nonexistent_profile() -> None:
    """Test profile_has_draft_mentors returns False for nonexistent profile."""
    with patch("sase.mentor_config.load_merged_config", return_value={}):
        result = profile_has_draft_mentors("nonexistent_profile")

    assert result is False
