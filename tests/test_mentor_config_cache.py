"""Tests for the mentor-profile cache in ``sase.config.mentor``.

Parsed profiles are memoized against the config token, so repeat calls hand
back the same list until the cache token is dropped.
"""

from unittest.mock import patch

import yaml
from sase.config import mentor as mentor_config
from sase.config.mentor import _load_mentor_profiles


def test_mentor_profiles_cache_returns_same_list() -> None:
    """Repeat calls to ``_load_mentor_profiles`` return the same list object."""
    yaml_content = """
mentor_profiles:
  - profile_name: code
    mentors:
      - mentor_name: code_quality
        role: "reviewer"
        focus_areas:
          - focus_name: comments
            description: "Doc the public API"
    file_globs:
      - "**/*.py"
"""
    data = yaml.safe_load(yaml_content)
    with patch("sase.config.mentor.load_merged_config", return_value=data):
        first = _load_mentor_profiles()
        second = _load_mentor_profiles()

    assert first is second
    assert len(first) == 1
    assert first[0].profile_name == "code"


def test_mentor_profiles_cache_invalidates_after_clear() -> None:
    """``clear_mentor_profiles_cache`` forces re-parse on the next call."""
    yaml_content = """
mentor_profiles:
  - profile_name: code
    mentors:
      - mentor_name: code_quality
        role: "reviewer"
        focus_areas:
          - focus_name: comments
            description: "Doc the public API"
    file_globs:
      - "**/*.py"
"""
    data = yaml.safe_load(yaml_content)
    with patch("sase.config.mentor.load_merged_config", return_value=data):
        first = _load_mentor_profiles()
        mentor_config._mentor_profiles_cache_token = None
        mentor_config._mentor_profiles_cache_value = None
        mentor_config._local_profile_names_cache_token = None
        mentor_config._local_profile_names_cache_value = None
        second = _load_mentor_profiles()

    assert first is not second
    assert first[0].profile_name == second[0].profile_name
