"""Tests for mentor profile and mentor retrieval functions."""

from sase.config.mentor import (
    MentorProfileConfig,
    get_mentor_from_profile,
)
from test_utils import make_mentor_config


def test_get_mentor_from_profile_found() -> None:
    """Test getting a mentor from a profile when it exists."""
    mentors = [
        make_mentor_config(mentor_name="mentor1"),
        make_mentor_config(mentor_name="mentor2"),
        make_mentor_config(mentor_name="mentor3"),
    ]
    profile = MentorProfileConfig(
        profile_name="test_profile",
        mentors=mentors,
        file_globs=["*.py"],
    )

    mentor = get_mentor_from_profile(profile, "mentor2")

    assert mentor is not None
    assert mentor.mentor_name == "mentor2"
    assert mentor.role == "test reviewer"


def test_get_mentor_from_profile_not_found() -> None:
    """Test getting a mentor from a profile when it doesn't exist."""
    mentors = [
        make_mentor_config(mentor_name="mentor1"),
        make_mentor_config(mentor_name="mentor2"),
    ]
    profile = MentorProfileConfig(
        profile_name="test_profile",
        mentors=mentors,
        file_globs=["*.py"],
    )

    mentor = get_mentor_from_profile(profile, "nonexistent")

    assert mentor is None
