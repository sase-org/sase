"""Shared test utilities for sase tests."""

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import patch

import yaml


@contextmanager
def mentor_config_from_yaml(yaml_content: str) -> Generator[dict, None, None]:
    """Context manager that parses YAML and patches load_merged_config."""
    data = yaml.safe_load(yaml_content)
    with patch("sase.mentor_config.load_merged_config", return_value=data):
        yield data
