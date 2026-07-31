"""Tests for loading and validating axe lumberjack config."""

from unittest.mock import patch

import pytest
import yaml

from sase.axe.config import (
    AxeConfig,
    AxeConfigError,
    ChopConfig,
    LumberjackConfig,
    load_axe_config,
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
    cfg = LumberjackConfig(
        name="hooks",
        description="Advance hook lifecycle state",
        interval=1,
        chops=chops,
    )
    assert cfg.name == "hooks"
    assert cfg.description == "Advance hook lifecycle state"
    assert cfg.interval == 1
    assert cfg.chops == chops


def test_lumberjack_config_default_chops() -> None:
    """Test LumberjackConfig defaults to empty chops list."""
    cfg = LumberjackConfig(
        name="test",
        description="Run test chops",
        interval=10,
    )
    assert cfg.chops == []


def test_axe_config_defaults() -> None:
    """Test AxeConfig has correct defaults."""
    cfg = AxeConfig()
    assert cfg.max_hook_runners == 3
    assert cfg.max_agent_runners == 3
    assert cfg.zombie_timeout_seconds == 7200
    assert cfg.lumberjack_log_max_bytes == 50 * 1024 * 1024
    assert cfg.lumberjack_log_temp_max_age_seconds == 300
    assert cfg.lumberjack_restart_backoff_max_seconds == 60
    assert cfg.verbose_lumberjack_diagnostics is False
    assert cfg.query == ""
    assert cfg.lumberjacks == {}


def test_load_axe_config_rejects_bare_string_chops() -> None:
    data = {
        "axe": {
            "lumberjacks": {
                "hooks": {
                    "description": "Run hook checks",
                    "interval": 1,
                    "chops": ["hook_checks"],
                }
            }
        }
    }

    with (
        patch("sase.axe.config.load_merged_config", return_value=data),
        pytest.raises(AxeConfigError) as exc_info,
    ):
        load_axe_config()

    diagnostic = exc_info.value.diagnostics[0]
    assert diagnostic.code == "required_missing"
    assert diagnostic.path == "axe.lumberjacks.hooks.chops.hook_checks.description"
    assert "list-form string entries cannot carry one" in diagnostic.message


def test_load_axe_config_requires_lumberjack_description() -> None:
    data = {
        "axe": {
            "lumberjacks": {
                "hooks": {
                    "interval": 1,
                    "chops": {
                        "hook_checks": {
                            "description": "Check hooks",
                        }
                    },
                }
            }
        }
    }

    with (
        patch("sase.axe.config.load_merged_config", return_value=data),
        pytest.raises(AxeConfigError) as exc_info,
    ):
        load_axe_config()

    diagnostic = exc_info.value.diagnostics[0]
    assert diagnostic.code == "required_missing"
    assert diagnostic.path == "axe.lumberjacks.hooks.description"


def test_load_axe_config_requires_chop_description() -> None:
    data = {
        "axe": {
            "lumberjacks": {
                "hooks": {
                    "description": "Run hook checks",
                    "interval": 1,
                    "chops": {"hook_checks": {}},
                }
            }
        }
    }

    with (
        patch("sase.axe.config.load_merged_config", return_value=data),
        pytest.raises(AxeConfigError) as exc_info,
    ):
        load_axe_config()

    diagnostic = exc_info.value.diagnostics[0]
    assert diagnostic.code == "required_missing"
    assert diagnostic.path == "axe.lumberjacks.hooks.chops.hook_checks.description"


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
  lumberjack_log_temp_max_age_seconds: 60
  lumberjack_restart_backoff_max_seconds: 9
  verbose_lumberjack_diagnostics: true
""")
    with patch("sase.axe.config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config.lumberjack_log_max_bytes == 12345
    assert config.lumberjack_log_temp_max_age_seconds == 60
    assert config.lumberjack_restart_backoff_max_seconds == 9
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


def test_load_axe_config_invalid_log_temp_max_age_fails_closed() -> None:
    data = yaml.safe_load("""
axe:
  lumberjack_log_temp_max_age_seconds: 0
""")
    with patch("sase.axe.config.load_merged_config", return_value=data):
        with pytest.raises(AxeConfigError) as exc_info:
            load_axe_config()

    assert "axe.lumberjack_log_temp_max_age_seconds" in str(exc_info.value)


def test_load_axe_config_invalid_lumberjack_restart_backoff_fails_closed() -> None:
    data = yaml.safe_load("""
axe:
  lumberjack_restart_backoff_max_seconds: 0
""")
    with patch("sase.axe.config.load_merged_config", return_value=data):
        with pytest.raises(AxeConfigError) as exc_info:
            load_axe_config()

    assert "axe.lumberjack_restart_backoff_max_seconds" in str(exc_info.value)


def test_load_axe_config_rejects_agent_chops_with_source_provenance() -> None:
    data = yaml.safe_load("""
axe:
  lumberjacks:
    audits:
      description: Run audit checks
      interval: 60
      chops:
        - name: recent
          description: Audit recent changes
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
    assert "bead_task_triage" in checks.chop_names
    assert "pr_submitted_checks" in checks.chop_names
    assert "cl_submitted_checks" not in checks.chop_names
    for lumberjack in config.lumberjacks.values():
        for chop in lumberjack.chops:
            assert chop.script is not None
            assert chop.script.startswith("sase_chop_")
