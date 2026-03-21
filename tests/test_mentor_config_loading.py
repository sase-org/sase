"""Tests for _load_mentor_profiles() function including error cases."""

import pytest
from sase.config.mentor import _load_mentor_profiles
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


def test_load_mentor_profiles_valid_new_schema() -> None:
    """Test loading valid mentor profiles with the new schema."""
    yaml_content = """
mentor_profiles:
  - profile_name: code
    mentors:
      - mentor_name: code_quality
        role: "senior code quality reviewer"
        focus_areas:
          - focus_name: comments
            description: "Ensure all public APIs have clear doc comments"
          - focus_name: shared_code
            description: "Identify duplicated code across files"
    file_globs:
      - "**/*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        profiles = _load_mentor_profiles()

    assert len(profiles) == 1
    assert profiles[0].profile_name == "code"
    assert len(profiles[0].mentors) == 1
    mentor = profiles[0].mentors[0]
    assert mentor.mentor_name == "code_quality"
    assert mentor.role == "senior code quality reviewer"
    assert len(mentor.focus_areas) == 2
    assert mentor.focus_areas[0].focus_name == "comments"
    assert mentor.focus_areas[1].focus_name == "shared_code"


def test_load_mentor_profiles_parses_first_commit() -> None:
    """Test that first_commit is parsed from YAML config."""
    yaml_content = """
mentor_profiles:
  - profile_name: complete_profile
    mentors:
      - mentor_name: complete
        role: "completeness reviewer"
        focus_areas:
          - focus_name: coverage
            description: "Check coverage"
    first_commit: true
    amend_note_regexes:
      - "\\\\[mentor:complete\\\\]"
"""
    with mentor_config_from_yaml(yaml_content):
        profiles = _load_mentor_profiles()

    assert len(profiles) == 1
    assert profiles[0].first_commit is True


def test_load_mentor_profiles_first_commit_defaults_to_false() -> None:
    """Test that first_commit defaults to False when not specified."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
    mentors:
      - mentor_name: quality
        role: "code reviewer"
        focus_areas:
          - focus_name: style
            description: "Check code style"
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        profiles = _load_mentor_profiles()

    assert profiles[0].first_commit is False


def test_load_mentor_profiles_focus_areas_not_list_raises() -> None:
    """Test loading raises ValueError when focus_areas is not a list."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
    mentors:
      - mentor_name: quality
        role: "code reviewer"
        focus_areas: "not_a_list"
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(ValueError, match="must be a list"):
            _load_mentor_profiles()


def test_load_mentor_profiles_focus_area_not_dict_raises() -> None:
    """Test loading raises ValueError when a focus area is not a dict."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
    mentors:
      - mentor_name: quality
        role: "code reviewer"
        focus_areas:
          - "not_a_dict"
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(ValueError, match="must be a dictionary"):
            _load_mentor_profiles()


def test_load_mentor_profiles_focus_area_missing_fields_raises() -> None:
    """Test loading raises ValueError when focus area lacks required fields."""
    yaml_content = """
mentor_profiles:
  - profile_name: test_profile
    mentors:
      - mentor_name: quality
        role: "code reviewer"
        focus_areas:
          - focus_name: style
    file_globs:
      - "*.py"
"""
    with mentor_config_from_yaml(yaml_content):
        with pytest.raises(
            ValueError, match="must have 'focus_name' and 'description' fields"
        ):
            _load_mentor_profiles()
