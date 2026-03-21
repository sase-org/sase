"""Tests for mentor profile and mentor retrieval functions."""

from sase.config.mentor import (
    MentorConfig,
    MentorProfileConfig,
    get_mentor_from_profile,
)


def test_get_mentor_from_profile_found() -> None:
    """Test getting a mentor from a profile when it exists."""
    mentors = [
        MentorConfig(mentor_name="mentor1", prompt="Prompt 1"),
        MentorConfig(mentor_name="mentor2", prompt="Prompt 2"),
        MentorConfig(mentor_name="mentor3", prompt="Prompt 3"),
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
