"""Tests for the axe lumberjack config module."""

from unittest.mock import patch

import yaml
import pytest

from sase.axe.config import (
    AxeConfig,
    AxeConfigError,
    ChopConfig,
    LumberjackConfig,
    _parse_lumberjacks,
    load_axe_config,
    _parse_duration,
)
from sase.config.core import ConfigLayer


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
    assert cfg.max_hook_runners == 3
    assert cfg.max_agent_runners == 3
    assert cfg.zombie_timeout_seconds == 7200
    assert cfg.lumberjack_log_max_bytes == 50 * 1024 * 1024
    assert cfg.verbose_lumberjack_diagnostics is False
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


def test_chop_config_run_every_defaults_to_none() -> None:
    """Test that run_every defaults to None (run every tick)."""
    chop = ChopConfig(name="test", description="")
    assert chop.run_every is None


def test_parse_duration_seconds() -> None:
    """Test parsing duration with seconds unit."""
    assert _parse_duration("30s") == 30


def test_parse_duration_minutes() -> None:
    """Test parsing duration with minutes unit."""
    assert _parse_duration("60m") == 3600


def test_parse_duration_hours() -> None:
    """Test parsing duration with hours unit."""
    assert _parse_duration("2h") == 7200


def test_parse_duration_days_and_compound_values() -> None:
    assert _parse_duration("1d2h30m") == 95_400


def test_parse_duration_invalid() -> None:
    """Test that invalid duration values return None."""
    assert _parse_duration("bad") is None
    assert _parse_duration(60) is None
    assert _parse_duration("") is None
    assert _parse_duration("10x") is None


def test_parse_lumberjacks_run_every_from_dict() -> None:
    """Test that run_every is parsed from duration string in dict chop entries."""
    raw = {
        "checks": {
            "interval": 60,
            "chops": [{"name": "slow_check", "run_every": "5m"}],
        },
    }
    result = _parse_lumberjacks(raw)
    assert result["checks"].chops[0].run_every == 300


def test_parse_lumberjacks_normalizes_declarative_chop_policy() -> None:
    raw = {
        "checks": {
            "interval": 60,
            "chops": [
                {
                    "name": "audit",
                    "inhibit_if": {
                        "changespec": {"name_prefix": "audit_"},
                        "agent_hood": [{"hood": "audit"}],
                    },
                    "trigger": {
                        "git.commits_since": {
                            "project": "sase",
                            "threshold": 5,
                            "checkpoint": "on_action_success",
                        }
                    },
                    "once_per": {"key": "audit:{proposal.id}", "capacity": 50},
                }
            ],
        }
    }

    chop = _parse_lumberjacks(raw)["checks"].chops[0]

    assert chop.inhibit_if == [
        {"provider": "changespec", "name_prefix": "audit_"},
        {"provider": "agent_hood", "hood": "audit"},
    ]
    assert chop.trigger == {
        "provider": "git.commits_since",
        "project": "sase",
        "threshold": 5,
        "checkpoint_policy": "on_action_success",
    }
    assert chop.once_per == {"key": "audit:{proposal.id}", "capacity": 50}


def test_parse_lumberjacks_run_every_invalid_becomes_none() -> None:
    """Test that invalid run_every values become None (run every tick)."""
    raw = {
        "checks": {
            "interval": 60,
            "chops": [
                {"name": "bare_int", "run_every": 60},
                {"name": "bad_string", "run_every": "bad"},
                {"name": "missing"},
            ],
        },
    }
    result = _parse_lumberjacks(raw)
    for chop in result["checks"].chops:
        assert chop.run_every is None


def test_parse_lumberjacks_string_chops_get_default_run_every() -> None:
    """Test that string chops get default run_every=None."""
    raw = {
        "hooks": {"interval": 1, "chops": ["hook_checks"]},
    }
    result = _parse_lumberjacks(raw)
    assert result["hooks"].chops[0].run_every is None


def test_parse_lumberjacks_chop_timeout() -> None:
    """Test that chop_timeout is parsed from the lumberjack config."""
    raw = {
        "hooks": {
            "interval": 5,
            "chop_timeout": "30s",
            "chops": [{"name": "hook_checks"}],
        },
    }
    result = _parse_lumberjacks(raw)
    assert result["hooks"].chop_timeout == 30


def test_parse_lumberjacks_chop_timeout_defaults_to_none() -> None:
    """Test that missing chop_timeout defaults to None."""
    raw = {
        "hooks": {"interval": 5, "chops": []},
    }
    result = _parse_lumberjacks(raw)
    assert result["hooks"].chop_timeout is None


def test_parse_lumberjacks_per_chop_timeout() -> None:
    """Test that per-chop timeout is parsed from dict chop entries."""
    raw = {
        "hooks": {
            "interval": 5,
            "chops": [
                {"name": "slow_chop", "timeout": "10s"},
                {"name": "fast_chop"},
            ],
        },
    }
    result = _parse_lumberjacks(raw)
    assert result["hooks"].chops[0].timeout == 10
    assert result["hooks"].chops[1].timeout is None


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


def test_load_axe_config_lumberjack_log_knobs() -> None:
    """Test lumberjack log cap and diagnostic verbosity config parsing."""
    data = yaml.safe_load("""
axe:
  lumberjack_log_max_bytes: 12345
  verbose_lumberjack_diagnostics: true
""")
    with patch("sase.axe.config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config.lumberjack_log_max_bytes == 12345
    assert config.verbose_lumberjack_diagnostics is True


def test_load_axe_config_invalid_lumberjack_log_cap_fails_closed() -> None:
    data = yaml.safe_load("""
axe:
  lumberjack_log_max_bytes: -1
""")
    with patch("sase.axe.config.load_merged_config", return_value=data):
        with pytest.raises(AxeConfigError) as exc_info:
            load_axe_config()

    assert "axe.lumberjack_log_max_bytes" in str(exc_info.value)


def test_load_axe_config_rejects_agent_chops_with_source_provenance() -> None:
    data = yaml.safe_load("""
axe:
  lumberjacks:
    audits:
      interval: 60
      chops:
        - name: recent
          agent: "#!audit"
""")
    layer = ConfigLayer(
        name="overlay:test.yml",
        path="/tmp/test.yml",
        exists=True,
        list_strategy="concatenate",
        data=data,
    )
    with (
        patch("sase.axe.config.load_merged_config", return_value=data),
        patch("sase.axe.config.load_config_layers", return_value=[layer]),
        pytest.raises(AxeConfigError) as exc_info,
    ):
        load_axe_config()

    message = str(exc_info.value)
    assert "agent_chop_removed" in message
    assert "axe.lumberjacks.audits.chops[0].agent" in message
    assert "overlay:test.yml:/tmp/test.yml" in message


def test_default_builtin_chops_use_explicit_full_script_names() -> None:
    from sase.config.core import _load_default_config

    data = _load_default_config()
    with patch("sase.axe.config.load_merged_config", return_value=data):
        config = load_axe_config()

    checks = config.lumberjacks["checks"]
    assert "pr_submitted_checks" in checks.chop_names
    assert "cl_submitted_checks" not in checks.chop_names
    for lumberjack in config.lumberjacks.values():
        for chop in lumberjack.chops:
            assert chop.script is not None
            assert chop.script.startswith("sase_chop_")
