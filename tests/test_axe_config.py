"""Tests for the axe_config module."""

from unittest.mock import patch

import yaml

from sase.axe_config import _AxeConfig, load_axe_config


def test_load_axe_config_all_fields() -> None:
    """Test loading config with all fields present."""
    data = yaml.safe_load("""
axe:
  full_check_interval: 600
  comment_check_interval: 120
  hook_interval: 5
  zombie_timeout_seconds: 3600
  max_runners: 10
""")
    with patch("sase.axe_config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config.full_check_interval == 600
    assert config.comment_check_interval == 120
    assert config.hook_interval == 5
    assert config.zombie_timeout_seconds == 3600
    assert config.max_runners == 10


def test_load_axe_config_partial_fields() -> None:
    """Test loading config with partial fields uses defaults for missing."""
    data = yaml.safe_load("""
axe:
  full_check_interval: 600
  max_runners: 10
""")
    with patch("sase.axe_config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config.full_check_interval == 600
    assert config.comment_check_interval == 60
    assert config.hook_interval == 1
    assert config.zombie_timeout_seconds == 7200
    assert config.max_runners == 10


def test_load_axe_config_no_axe_section() -> None:
    """Test loading config with no axe section returns all defaults."""
    data = yaml.safe_load("""
metahooks:
  - name: scuba
    hook_command: bb_rabbit_test
    output_regex: "test"
""")
    with patch("sase.axe_config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config == _AxeConfig()


def test_load_axe_config_missing_file() -> None:
    """Test loading config with missing file returns all defaults."""
    with patch("sase.axe_config.load_merged_config", return_value={}):
        config = load_axe_config()

    assert config == _AxeConfig()


def test_load_axe_config_axe_section_not_dict() -> None:
    """Test loading config when axe section is not a dict returns defaults."""
    data = yaml.safe_load("""
axe: "not a dict"
""")
    with patch("sase.axe_config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config == _AxeConfig()


def test_load_axe_config_data_not_dict() -> None:
    """Test loading config when top-level data is not a dict returns defaults."""
    with patch("sase.axe_config.load_merged_config", return_value={}):
        config = load_axe_config()

    assert config == _AxeConfig()
