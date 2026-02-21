"""Tests for the axe lumberjack config module."""

from unittest.mock import patch

import yaml

from sase.axe.config import (
    AxeConfig,
    LumberjackConfig,
    _parse_lumberjacks,
    load_axe_config,
)


def test_lumberjack_config_basic() -> None:
    """Test LumberjackConfig dataclass creation."""
    cfg = LumberjackConfig(name="hooks", interval=1, chops=["hook_checks"])
    assert cfg.name == "hooks"
    assert cfg.interval == 1
    assert cfg.chops == ["hook_checks"]


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


def test_parse_lumberjacks_basic() -> None:
    """Test parsing a simple lumberjacks dict."""
    raw = {
        "hooks": {"interval": 1, "chops": ["hook_checks", "mentor_checks"]},
        "checks": {"interval": 300, "chops": ["cl_submitted_checks"]},
    }
    result = _parse_lumberjacks(raw)
    assert len(result) == 2
    assert result["hooks"].name == "hooks"
    assert result["hooks"].interval == 1
    assert result["hooks"].chops == ["hook_checks", "mentor_checks"]
    assert result["checks"].interval == 300


def test_parse_lumberjacks_skips_non_dict_entries() -> None:
    """Test that non-dict entries are skipped."""
    raw = {
        "hooks": {"interval": 1, "chops": []},
        "bad": "not a dict",
    }
    result = _parse_lumberjacks(raw)
    assert len(result) == 1
    assert "hooks" in result


def test_parse_lumberjacks_default_interval() -> None:
    """Test that missing interval defaults to 1."""
    raw = {"test": {"chops": ["foo"]}}
    result = _parse_lumberjacks(raw)
    assert result["test"].interval == 1


def test_parse_lumberjacks_default_chops() -> None:
    """Test that missing chops defaults to empty list."""
    raw = {"test": {"interval": 5}}
    result = _parse_lumberjacks(raw)
    assert result["test"].chops == []


def test_load_axe_config_gets_defaults_from_default_config() -> None:
    """Test that load_axe_config picks up defaults from default_config.yml."""
    # With no user overrides, default_config.yml provides everything
    config = load_axe_config()
    assert config.max_runners == 5
    assert config.zombie_timeout_seconds == 7200
    assert len(config.lumberjacks) == 4
    assert set(config.lumberjacks.keys()) == {
        "hooks",
        "checks",
        "comments",
        "housekeeping",
    }


def test_load_axe_config_default_hooks_lumberjack() -> None:
    """Test default hooks lumberjack has expected chops from default_config.yml."""
    config = load_axe_config()
    hooks = config.lumberjacks["hooks"]
    assert hooks.interval == 1
    assert "hook_checks" in hooks.chops
    assert "mentor_checks" in hooks.chops
    assert "suffix_transforms" in hooks.chops
    assert "wait_checks" in hooks.chops
    assert len(hooks.chops) == 8


def test_load_axe_config_default_checks_lumberjack() -> None:
    """Test default checks lumberjack configuration."""
    config = load_axe_config()
    checks = config.lumberjacks["checks"]
    assert checks.interval == 300
    assert "cl_submitted_checks" in checks.chops
    assert "stale_running_cleanup" in checks.chops


def test_load_axe_config_default_comments_lumberjack() -> None:
    """Test default comments lumberjack configuration."""
    config = load_axe_config()
    comments = config.lumberjacks["comments"]
    assert comments.interval == 60
    assert comments.chops == ["comment_checks"]


def test_load_axe_config_default_housekeeping_lumberjack() -> None:
    """Test default housekeeping lumberjack configuration."""
    config = load_axe_config()
    hk = config.lumberjacks["housekeeping"]
    assert hk.interval == 3600
    assert hk.chops == ["error_digest"]


def test_load_axe_config_with_lumberjacks_key() -> None:
    """Test loading config when lumberjacks key is present."""
    data = yaml.safe_load("""
axe:
  max_runners: 8
  zombie_timeout_seconds: 3600
  query: "my_query"
  lumberjacks:
    hooks:
      interval: 2
      chops:
        - hook_checks
        - mentor_checks
    checks:
      interval: 600
      chops:
        - cl_submitted_checks
""")
    with patch("sase.axe.config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config.max_runners == 8
    assert config.zombie_timeout_seconds == 3600
    assert config.query == "my_query"
    assert len(config.lumberjacks) == 2
    assert config.lumberjacks["hooks"].interval == 2
    assert config.lumberjacks["hooks"].chops == ["hook_checks", "mentor_checks"]
    assert config.lumberjacks["checks"].interval == 600


def test_load_axe_config_no_axe_section() -> None:
    """Test loading config with no axe section returns AxeConfig defaults."""
    data = yaml.safe_load("""
metahooks:
  - name: test
""")
    with patch("sase.axe.config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config.max_runners == 5
    assert config.lumberjacks == {}


def test_load_axe_config_empty_data() -> None:
    """Test loading config with empty data returns AxeConfig defaults."""
    with patch("sase.axe.config.load_merged_config", return_value={}):
        config = load_axe_config()

    assert config == AxeConfig()


def test_load_axe_config_axe_not_dict() -> None:
    """Test loading config when axe section is not a dict."""
    data = yaml.safe_load('axe: "not a dict"')
    with patch("sase.axe.config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config.max_runners == 5
    assert config.lumberjacks == {}


def test_load_axe_config_lumberjacks_not_dict() -> None:
    """Test that non-dict lumberjacks value results in empty lumberjacks."""
    data = yaml.safe_load("""
axe:
  max_runners: 3
  lumberjacks: "not a dict"
""")
    with patch("sase.axe.config.load_merged_config", return_value=data):
        config = load_axe_config()

    assert config.max_runners == 3
    assert config.lumberjacks == {}


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
