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
        ValueError, match="must have at least one of: file_globs, diff_regexes"
    ):
        MentorProfileConfig(
            profile_name="invalid_profile",
            mentors=mentors,
        )
