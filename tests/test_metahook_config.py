"""Tests for the metahook_config module."""

from unittest.mock import patch

import pytest
import yaml

from sase.config.metahook import (
    MetahookConfig,
    _get_all_metahooks,
    _load_metahooks,
    find_matching_metahook,
)


def test_metahook_config_dataclass() -> None:
    """Test MetahookConfig dataclass."""
    config = MetahookConfig(
        name="scuba",
        hook_command="bb_rabbit_test",
        output_regex="Expected: Scuba Result PASSED",
    )

    assert config.name == "scuba"
    assert config.hook_command == "bb_rabbit_test"
    assert config.output_regex == "Expected: Scuba Result PASSED"


def test_load_metahooks_missing_key_returns_empty() -> None:
    """Test loading when metahooks key is missing returns empty list."""
    data = yaml.safe_load("""
snippets:
  foo: "bar"
""")
    with patch("sase.config.metahook.load_merged_config", return_value=data):
        metahooks = _load_metahooks()

    assert metahooks == []


def test_load_metahooks_invalid_not_list_raises_error() -> None:
    """Test loading raises ValueError when metahooks is not a list."""
    data = yaml.safe_load("""
metahooks:
  scuba: "value"
""")
    with patch("sase.config.metahook.load_merged_config", return_value=data):
        with pytest.raises(ValueError, match="must be a list"):
            _load_metahooks()


def test_load_metahooks_item_not_dict_raises_error() -> None:
    """Test loading raises ValueError when metahook item is not a dictionary."""
    data = yaml.safe_load("""
metahooks:
  - "just_a_string"
""")
    with patch("sase.config.metahook.load_merged_config", return_value=data):
        with pytest.raises(ValueError, match="must be a dictionary"):
            _load_metahooks()


def test_load_metahooks_missing_name_raises_error() -> None:
    """Test loading raises ValueError when metahook is missing name field."""
    data = yaml.safe_load("""
metahooks:
  - hook_command: bb_rabbit_test
    output_regex: "test"
""")
    with patch("sase.config.metahook.load_merged_config", return_value=data):
        with pytest.raises(ValueError, match="missing required field: name"):
            _load_metahooks()


def test__get_all_metahooks_config_error() -> None:
    """Test that get_all_metahooks returns empty list on config errors."""
    with patch("sase.config.metahook.load_merged_config", return_value={}):
        metahooks = _get_all_metahooks()

    assert metahooks == []


def test_find_matching_metahook_command_no_match() -> None:
    """Test find_matching_metahook when command doesn't match."""
    data = yaml.safe_load("""
metahooks:
  - name: scuba
    hook_command: bb_rabbit_test
    output_regex: "Expected: Scuba"
""")
    with patch("sase.config.metahook.load_merged_config", return_value=data):
        result = find_matching_metahook(
            "different_command",
            "Output: Expected: Scuba Result PASSED",
        )

    assert result is None


def test_find_matching_metahook_regex_no_match() -> None:
    """Test find_matching_metahook when regex doesn't match."""
    data = yaml.safe_load("""
metahooks:
  - name: scuba
    hook_command: bb_rabbit_test
    output_regex: "Expected: Scuba"
""")
    with patch("sase.config.metahook.load_merged_config", return_value=data):
        result = find_matching_metahook(
            "bb_rabbit_test",
            "Some different output without the expected pattern",
        )

    assert result is None


def test_find_matching_metahook_invalid_regex_skipped() -> None:
    """Test find_matching_metahook skips metahooks with invalid regex."""
    data = yaml.safe_load("""
metahooks:
  - name: invalid
    hook_command: bb_rabbit
    output_regex: "[invalid regex("
  - name: valid
    hook_command: bb_rabbit
    output_regex: "test"
""")
    with patch("sase.config.metahook.load_merged_config", return_value=data):
        result = find_matching_metahook(
            "bb_rabbit_test",
            "some test output",
        )

    # Should skip the invalid regex and match the valid one
    assert result is not None
    assert result.name == "valid"
