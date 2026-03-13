"""Tests for the axe jack config module."""

from unittest.mock import patch

import yaml

from sase.axe.config import (
    AxeConfig,
    ChopConfig,
    JackConfig,
    _parse_jacks,
    load_axe_config,
)


def test_chop_config_basic() -> None:
    """Test ChopConfig dataclass creation."""
    chop = ChopConfig(name="hook_checks", description="Check hooks")
    assert chop.name == "hook_checks"
    assert chop.description == "Check hooks"


def test_jack_config_basic() -> None:
    """Test JackConfig dataclass creation."""
    chops = [ChopConfig(name="hook_checks", description="Check hooks")]
    cfg = JackConfig(name="hooks", interval=1, chops=chops)
    assert cfg.name == "hooks"
    assert cfg.interval == 1
    assert cfg.chops == chops


def test_jack_config_default_chops() -> None:
    """Test JackConfig defaults to empty chops list."""
    cfg = JackConfig(name="test", interval=10)
    assert cfg.chops == []


def test_axe_config_defaults() -> None:
    """Test AxeConfig has correct defaults."""
    cfg = AxeConfig()
    assert cfg.max_hook_runners == 3
    assert cfg.max_agent_runners == 3
    assert cfg.zombie_timeout_seconds == 7200
    assert cfg.query == ""
    assert cfg.jacks == {}


def test_parse_jacks_string_chops_backward_compat() -> None:
    """Test that plain string chops are parsed with empty descriptions."""
    raw = {
        "hooks": {"interval": 1, "chops": ["hook_checks", "mentor_checks"]},
    }
    result = _parse_jacks(raw)
    assert result["hooks"].chop_names == ["hook_checks", "mentor_checks"]
    assert result["hooks"].chops[0].description == ""
    assert result["hooks"].chops[1].description == ""


def test_parse_jacks_skips_non_dict_entries() -> None:
    """Test that non-dict entries are skipped."""
    raw = {
        "hooks": {"interval": 1, "chops": []},
        "bad": "not a dict",
    }
    result = _parse_jacks(raw)
    assert len(result) == 1
    assert "hooks" in result


def test_chop_config_run_every_defaults_to_one() -> None:
    """Test that run_every defaults to 1."""
    chop = ChopConfig(name="test", description="")
    assert chop.run_every == 1


def test_parse_jacks_run_every_from_dict() -> None:
    """Test that run_every is parsed from dict chop entries."""
    raw = {
        "checks": {
            "interval": 60,
            "chops": [{"name": "slow_check", "run_every": 5}],
        },
    }
    result = _parse_jacks(raw)
    assert result["checks"].chops[0].run_every == 5


def test_parse_jacks_run_every_clamps_invalid() -> None:
    """Test that invalid run_every values are clamped to 1."""
    raw = {
        "checks": {
            "interval": 60,
            "chops": [
                {"name": "zero", "run_every": 0},
                {"name": "negative", "run_every": -3},
                {"name": "string", "run_every": "bad"},
            ],
        },
    }
    result = _parse_jacks(raw)
    for chop in result["checks"].chops:
        assert chop.run_every == 1


def test_parse_jacks_string_chops_get_default_run_every() -> None:
    """Test that string chops get default run_every=1."""
    raw = {
        "hooks": {"interval": 1, "chops": ["hook_checks"]},
    }
    result = _parse_jacks(raw)
    assert result["hooks"].chops[0].run_every == 1


def test_load_axe_config_empty_data() -> None:
    """Test loading config with empty data returns AxeConfig defaults."""
    with patch("sase.axe.config.load_merged_config", return_value={}):
        config = load_axe_config()

    assert config == AxeConfig()


def test_load_axe_config_partial_fields_use_defaults() -> None:
    """Test that missing fields use defaults."""
    data = yaml.safe_load("""
axe:
  max_hook_runners: 7
""")
    with patch("sase.axe.config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config.max_hook_runners == 7
    assert config.zombie_timeout_seconds == 7200
    assert config.query == ""
