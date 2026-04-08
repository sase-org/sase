"""Tests for telemetry config loading."""

from unittest.mock import patch

from sase.telemetry._config import (
    TelemetryConfig,
    get_telemetry_config,
    reset_telemetry_config,
)


def setup_function() -> None:
    reset_telemetry_config()


def teardown_function() -> None:
    reset_telemetry_config()


def test_default_config_values() -> None:
    cfg = TelemetryConfig()
    assert cfg.enabled is False
    assert cfg.exposition_port == 9464
    assert cfg.pushgateway_url == "localhost:9091"


def test_config_is_frozen() -> None:
    cfg = TelemetryConfig()
    try:
        cfg.enabled = True  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError")
    except AttributeError:
        pass


def test_get_telemetry_config_loads_from_merged() -> None:
    merged = {
        "telemetry": {
            "enabled": True,
            "prometheus": {
                "exposition_port": 9999,
                "pushgateway_url": "push.example.com:9091",
            },
        }
    }
    with patch("sase.config.core.load_merged_config", return_value=merged):
        cfg = get_telemetry_config()

    assert cfg.enabled is True
    assert cfg.exposition_port == 9999
    assert cfg.pushgateway_url == "push.example.com:9091"


def test_get_telemetry_config_caches() -> None:
    merged = {"telemetry": {"enabled": True, "prometheus": {}}}
    with patch("sase.config.core.load_merged_config", return_value=merged) as m:
        cfg1 = get_telemetry_config()
        cfg2 = get_telemetry_config()

    assert cfg1 is cfg2
    assert m.call_count == 1


def test_get_telemetry_config_missing_section() -> None:
    with patch("sase.config.core.load_merged_config", return_value={}):
        cfg = get_telemetry_config()

    assert cfg.enabled is False
    assert cfg.exposition_port == 9464


def test_get_telemetry_config_non_dict_section() -> None:
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"telemetry": "invalid"},
    ):
        cfg = get_telemetry_config()

    assert cfg.enabled is False


def test_get_telemetry_config_non_dict_prometheus() -> None:
    with patch(
        "sase.config.core.load_merged_config",
        return_value={"telemetry": {"enabled": True, "prometheus": "bad"}},
    ):
        cfg = get_telemetry_config()

    assert cfg.enabled is True
    assert cfg.exposition_port == 9464


def test_reset_clears_cache() -> None:
    merged1 = {"telemetry": {"enabled": True, "prometheus": {}}}
    merged2 = {"telemetry": {"enabled": False, "prometheus": {}}}
    with patch("sase.config.core.load_merged_config", return_value=merged1):
        cfg1 = get_telemetry_config()
    reset_telemetry_config()
    with patch("sase.config.core.load_merged_config", return_value=merged2):
        cfg2 = get_telemetry_config()

    assert cfg1.enabled is True
    assert cfg2.enabled is False
