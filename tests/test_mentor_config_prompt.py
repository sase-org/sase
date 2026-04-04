"""Tests for MentorConfig role and focus_areas field functionality."""

import logging

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


def test_load_mentor_profiles_without_role_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that mentor without role skips the profile."""
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
        with caplog.at_level(logging.WARNING):
            profiles = _load_mentor_profiles()

    assert profiles == []
    assert "Skipping invalid mentor profile 'test_profile'" in caplog.text


def test_load_mentor_profiles_without_focus_areas_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that mentor without focus_areas skips the profile."""
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
        with caplog.at_level(logging.WARNING):
            profiles = _load_mentor_profiles()

    assert profiles == []
    assert "Skipping invalid mentor profile 'test_profile'" in caplog.text


def test_load_mentor_profiles_without_mentor_name_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that mentor without mentor_name skips the profile."""
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
        with caplog.at_level(logging.WARNING):
            profiles = _load_mentor_profiles()

    assert profiles == []
    assert "Skipping invalid mentor profile 'test_profile'" in caplog.text
