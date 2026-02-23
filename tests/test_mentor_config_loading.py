"""Tests for _load_mentor_profiles() function including error cases."""

import pytest
from sase.mentor_config import _load_mentor_profiles
from test_utils import mentor_config_from_yaml


def test_load_mentor_profiles_missing_key_returns_empty() -> None:
    """Test loading when mentor_profiles key is missing returns empty list."""
    yaml_content = """
other_key:
  - value: test
"""
    with mentor_config_from_yaml(yaml_content):
        profiles = _load_mentor_profiles()

    assert profiles == []


def test_load_mentor_profiles_invalid_mentor_not_dict() -> None:
    """Test loading raises ValueError when mentor is not a dictionary."""
    yaml_content = """
mentor_profiles:
  - profile_name: profile1
    mentors:
      - "just_a_string"
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(ValueError, match="must be a dictionary"):
            _load_mentor_profiles()


def test_load_mentor_profiles_config_not_dict() -> None:
    """Test loading raises ValueError when config is not a dictionary."""
    yaml_content = """
- just_a_list_item
- another_item
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(ValueError, match="Config must be a dictionary"):
            _load_mentor_profiles()


def test_load_mentor_profiles_profile_not_dict() -> None:
    """Test loading raises ValueError when mentor profile is not a dictionary."""
    yaml_content = """
mentor_profiles:
  - "just_a_string_profile"
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(
            ValueError, match="Each mentor profile must be a dictionary"
        ):
            _load_mentor_profiles()


def test_load_mentor_profiles_profile_missing_fields() -> None:
    """Test loading raises ValueError when profile is missing required fields."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(
            ValueError, match="must have 'profile_name' and 'mentors' fields"
        ):
            _load_mentor_profiles()


def test_load_mentor_profiles_mentors_not_list() -> None:
    """Test loading raises ValueError when mentors field is not a list."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
    mentors: "not_a_list"
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(ValueError, match="'mentors' field must be a list"):
            _load_mentor_profiles()


def test_load_mentor_profiles_simple_prompt_name_derivation() -> None:
    """Test that simple prompt (no namespace) derives name correctly."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
    mentors:
      - prompt: "#foo"
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        profiles = _load_mentor_profiles()

    # Should derive name from #foo -> foo
    assert profiles[0].mentors[0].mentor_name == "foo"
    assert profiles[0].mentors[0].prompt == "#foo"
