"""Tests for _load_mentor_profiles() function including error cases."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

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


def test_load_mentor_profiles_parses_explicit_projects() -> None:
    """Test that explicit projects field is parsed from YAML."""
    yaml_content = """
mentor_profiles:
  - profile_name: code
    mentors:
      - mentor_name: quality
        role: "code reviewer"
        focus_areas:
          - focus_name: style
            description: "Check style"
    file_globs:
      - "*.py"
    projects:
      - sase
      - bug
"""
    with mentor_config_from_yaml(yaml_content):
        profiles = _load_mentor_profiles()

    assert len(profiles) == 1
    assert profiles[0].projects == ["sase", "bug"]


def test_load_mentor_profiles_auto_tags_local_profiles(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Test that local config profiles get auto-tagged with detected project."""
    yaml_content = """
mentor_profiles:
  - profile_name: gotchas
    mentors:
      - mentor_name: gotcha_checker
        role: "gotcha reviewer"
        focus_areas:
          - focus_name: gotchas
            description: "Check for gotchas"
    file_globs:
      - "*.py"
"""
    (tmp_path / "sase.yml").write_text(yaml_content)
    monkeypatch.chdir(tmp_path)

    with mentor_config_from_yaml(yaml_content):
        with patch("sase.xprompt.loader.detect_project", return_value="sase"):
            profiles = _load_mentor_profiles()

    assert len(profiles) == 1
    assert profiles[0].projects == ["sase"]


def test_load_mentor_profiles_no_auto_tag_for_non_local_profiles(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Test that non-local profiles don't get auto-tagged."""
    yaml_content = """
mentor_profiles:
  - profile_name: plugin_profile
    mentors:
      - mentor_name: checker
        role: "reviewer"
        focus_areas:
          - focus_name: check
            description: "Check things"
    file_globs:
      - "*.py"
"""
    # Local sase.yml has no mentor profiles matching "plugin_profile"
    (tmp_path / "sase.yml").write_text("other_key: value\n")
    monkeypatch.chdir(tmp_path)

    with mentor_config_from_yaml(yaml_content):
        with patch("sase.xprompt.loader.detect_project", return_value="sase"):
            profiles = _load_mentor_profiles()

    assert len(profiles) == 1
    assert profiles[0].projects is None


def test_load_mentor_profiles_no_auto_tag_when_project_not_detected(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Test that local profiles aren't auto-tagged when detect_project returns None."""
    yaml_content = """
mentor_profiles:
  - profile_name: gotchas
    mentors:
      - mentor_name: gotcha_checker
        role: "gotcha reviewer"
        focus_areas:
          - focus_name: gotchas
            description: "Check for gotchas"
    file_globs:
      - "*.py"
"""
    (tmp_path / "sase.yml").write_text(yaml_content)
    monkeypatch.chdir(tmp_path)

    with mentor_config_from_yaml(yaml_content):
        with patch("sase.xprompt.loader.detect_project", return_value=None):
            profiles = _load_mentor_profiles()

    assert len(profiles) == 1
    assert profiles[0].projects is None
