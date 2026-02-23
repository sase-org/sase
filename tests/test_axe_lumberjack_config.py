"""Tests for the axe lumberjack config module."""

from unittest.mock import patch

import yaml

from sase.axe.config import (
    AxeConfig,
    ChopConfig,
    LumberjackConfig,
    _parse_lumberjacks,
    load_axe_config,
)


def test_chop_config_basic() -> None:
    """Test ChopConfig dataclass creation."""
    chop = ChopConfig(name="hook_checks", description="Check hooks")
    assert chop.name == "hook_checks"
    assert chop.description == "Check hooks"


def test_lumberjack_config_basic() -> None:
    """Test LumberjackConfig dataclass creation."""
    chops = [ChopConfig(name="hook_checks", description="Check hooks")]
    cfg = LumberjackConfig(name="hooks", interval=1, chops=chops)
    assert cfg.name == "hooks"
    assert cfg.interval == 1
    assert cfg.chops == chops


def test_lumberjack_config_default_chops() -> None:
    """Test LumberjackConfig defaults to empty chops list."""
    cfg = LumberjackConfig(name="test", interval=10)
    assert cfg.chops == []


def test_axe_config_defaults() -> None:
    """Test AxeConfig has correct defaults."""
    cfg = AxeConfig()
    assert cfg.max_runners == 5
    assert cfg.zombie_timeout_seconds == 7200
    assert cfg.query == ""
    assert cfg.lumberjacks == {}


def test_parse_lumberjacks_string_chops_backward_compat() -> None:
    """Test that plain string chops are parsed with empty descriptions."""
    raw = {
        "hooks": {"interval": 1, "chops": ["hook_checks", "mentor_checks"]},
    }
    result = _parse_lumberjacks(raw)
    assert result["hooks"].chop_names == ["hook_checks", "mentor_checks"]
    assert result["hooks"].chops[0].description == ""
    assert result["hooks"].chops[1].description == ""


def test_parse_lumberjacks_skips_non_dict_entries() -> None:
    """Test that non-dict entries are skipped."""
    raw = {
        "hooks": {"interval": 1, "chops": []},
        "bad": "not a dict",
    }
    result = _parse_lumberjacks(raw)
    assert len(result) == 1
    assert "hooks" in result


def test_load_axe_config_empty_data() -> None:
    """Test loading config with empty data returns AxeConfig defaults."""
    with patch("sase.axe.config.load_merged_config", return_value={}):
        config = load_axe_config()

    assert config == AxeConfig()


def test_load_axe_config_partial_fields_use_defaults() -> None:
    """Test that missing fields use defaults."""
    data = yaml.safe_load("""
axe:
  max_runners: 7
""")
    with patch("sase.axe.config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config.max_runners == 7
    assert config.zombie_timeout_seconds == 7200
    assert config.query == ""
