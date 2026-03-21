"""Shared test utilities for sase tests."""

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import patch

import yaml

from sase.config.mentor import MentorConfig, MentorFocusArea


def make_mentor_config(
    mentor_name: str = "test_mentor",
    role: str = "test reviewer",
    focus_areas: list[MentorFocusArea] | None = None,
) -> MentorConfig:
    """Create a MentorConfig with sensible defaults for tests."""
    if focus_areas is None:
        focus_areas = [
            MentorFocusArea(focus_name="quality", description="Check code quality")
        ]
    return MentorConfig(
        mentor_name=mentor_name,
        role=role,
        focus_areas=focus_areas,
    )


@contextmanager
def mentor_config_from_yaml(yaml_content: str) -> Generator[dict, None, None]:
    """Context manager that parses YAML and patches load_merged_config."""
    data = yaml.safe_load(yaml_content)
    with patch("sase.config.mentor.load_merged_config", return_value=data):
        yield data
