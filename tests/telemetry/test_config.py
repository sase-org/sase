"""Tests for telemetry config loading."""

from unittest.mock import patch

from sase.telemetry._config import (
    _RetentionConfig,
    _TelemetryConfig,
    get_telemetry_config,
)
from tests.telemetry.conftest import reset_telemetry_config


def setup_function() -> None:
    reset_telemetry_config()


def teardown_function() -> None:
    reset_telemetry_config()


def test_default_config_values() -> None:
    cfg = _TelemetryConfig()
    assert cfg.enabled is True
    assert cfg.flush_interval_seconds == 15
    assert cfg.retention == _RetentionConfig()
    assert cfg.resolved_store_path.name == "metrics.sqlite"


def test_config_is_frozen() -> None:
    cfg = _TelemetryConfig()
    try:
        cfg.enabled = True  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError")
    except AttributeError:
        pass


def test_get_telemetry_config_loads_from_merged() -> None:
    merged = {
        "telemetry": {
            "enabled": True,
            "flush_interval_seconds": 30,
            "retention": {
                "raw_seconds": 60,
                "rollup_5m_seconds": 120,
                "rollup_1h_seconds": 180,
            },
        }
    }
    with patch("sase.config.core.load_merged_config", return_value=merged):
        cfg = get_telemetry_config()

    assert cfg.enabled is True
    assert cfg.flush_interval_seconds == 30
    assert cfg.retention.raw_seconds == 60
    assert cfg.retention.rollup_5m_seconds == 120
    assert cfg.retention.rollup_1h_seconds == 180


def test_get_telemetry_config_caches() -> None:
    merged = {"telemetry": {"enabled": True}}
    with patch("sase.config.core.load_merged_config", return_value=merged) as m:
        cfg1 = get_telemetry_config()
        cfg2 = get_telemetry_config()

    assert cfg1 is cfg2
    assert m.call_count == 1


def test_get_telemetry_config_missing_section() -> None:
    with patch("sase.config.core.load_merged_config", return_value={}):
        cfg = get_telemetry_config()

    assert cfg.enabled is True
    assert cfg.flush_interval_seconds == 15


def test_get_telemetry_config_non_dict_section() -> None:
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"telemetry": "invalid"},
    ):
        cfg = get_telemetry_config()

    assert cfg.enabled is True


def test_get_telemetry_config_ignores_legacy_prometheus_block() -> None:
    with patch(
        "sase.config.core.load_merged_config",
        return_value={
            "telemetry": {
                "enabled": True,
                "prometheus": {
                    "exposition_port": 9999,
                    "pushgateway_url": "push.example.com:9091",
                },
            }
        },
    ):
        cfg = get_telemetry_config()

    assert cfg.enabled is True
    assert cfg.flush_interval_seconds == 15
    assert cfg.retention == _RetentionConfig()


def test_reset_clears_cache() -> None:
    merged1 = {"telemetry": {"enabled": True}}
    merged2 = {"telemetry": {"enabled": False}}
    with patch("sase.config.core.load_merged_config", return_value=merged1):
        cfg1 = get_telemetry_config()
    reset_telemetry_config()
    with patch("sase.config.core.load_merged_config", return_value=merged2):
        cfg2 = get_telemetry_config()

    assert cfg1.enabled is True
    assert cfg2.enabled is False
