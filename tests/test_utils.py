"""Shared test utilities for sase tests."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import yaml

from sase.ace.changespec import ChangeSpec
from sase.config.mentor import MentorConfig, _MentorFocusArea


def make_mentor_config(
    mentor_name: str = "test_mentor",
    role: str = "test reviewer",
    focus_areas: list[_MentorFocusArea] | None = None,
) -> MentorConfig:
    """Create a MentorConfig with sensible defaults for tests."""
    if focus_areas is None:
        focus_areas = [
            _MentorFocusArea(focus_name="quality", description="Check code quality")
        ]
    return MentorConfig(
        mentor_name=mentor_name,
        role=role,
        focus_areas=focus_areas,
    )


def build_changespec(**kwargs: Any) -> ChangeSpec:
    """Create a ChangeSpec with sensible defaults for tests."""
    defaults: dict[str, Any] = {
        "name": "test-cl",
        "description": "Test description",
        "parent": None,
        "cl": None,
        "status": "Ready",
        "test_targets": None,
        "kickstart": None,
        "file_path": "/tmp/test.md",
        "line_number": 1,
        "commits": None,
        "hooks": None,
        "comments": None,
        "mentors": None,
    }
    defaults.update(kwargs)
    return ChangeSpec(**defaults)  # type: ignore[arg-type]


@contextmanager
def mentor_config_from_yaml(yaml_content: str) -> Generator[dict, None, None]:
    """Context manager that parses YAML and patches load_merged_config."""
    data = yaml.safe_load(yaml_content)
    with patch("sase.config.mentor.load_merged_config", return_value=data):
        yield data
