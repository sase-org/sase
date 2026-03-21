"""Tests for MentorConfig role and focus_areas field functionality."""

import pytest
from sase.config.mentor import _MentorFocusArea, _load_mentor_profiles
from test_utils import make_mentor_config, mentor_config_from_yaml


def test_mentor_config_with_role_and_focus_areas() -> None:
    """Test MentorConfig with role and focus_areas fields."""
    focus_areas = [
        _MentorFocusArea(focus_name="comments", description="Check doc comments"),
    ]
    config = make_mentor_config(
        mentor_name="aaa",
        role="code quality expert",
        focus_areas=focus_areas,
    )

    assert config.mentor_name == "aaa"
    assert config.role == "code quality expert"
    assert len(config.focus_areas) == 1
    assert config.focus_areas[0].focus_name == "comments"


def test_load_mentor_profiles_without_role_raises() -> None:
    """Test that mentor without role raises ValueError."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
    mentors:
      - mentor_name: invalid
        focus_areas:
          - focus_name: quality
            description: "Check quality"
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(ValueError, match="must have 'role' field"):
            _load_mentor_profiles()


def test_load_mentor_profiles_without_focus_areas_raises() -> None:
    """Test that mentor without focus_areas raises ValueError."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
    mentors:
      - mentor_name: invalid
        role: "test reviewer"
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(ValueError, match="must have 'focus_areas' field"):
            _load_mentor_profiles()


def test_load_mentor_profiles_without_mentor_name_raises() -> None:
    """Test that mentor without mentor_name raises ValueError."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
    mentors:
      - role: "test reviewer"
        focus_areas:
          - focus_name: quality
            description: "Check quality"
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(ValueError, match="must have 'mentor_name' field"):
            _load_mentor_profiles()
