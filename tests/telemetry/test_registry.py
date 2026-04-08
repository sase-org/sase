"""Tests for telemetry registry management."""

from unittest.mock import patch

from sase.telemetry._config import TelemetryConfig, reset_telemetry_config
from sase.telemetry._registry import init_telemetry, is_initialized, reset_registry
from sase.telemetry._stubs import StubCounter


def setup_function() -> None:
    reset_registry()
    reset_telemetry_config()


def teardown_function() -> None:
    reset_registry()
    reset_telemetry_config()


def test_init_telemetry_disabled_keeps_stubs() -> None:
    cfg = TelemetryConfig(enabled=False)
    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()

    from sase.telemetry import metrics as m

    assert isinstance(m.AGENT_RUNS, StubCounter)


def test_init_telemetry_is_idempotent() -> None:
    cfg = TelemetryConfig(enabled=False)
    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()
        init_telemetry()  # second call is a no-op

    assert is_initialized()


def test_is_initialized_false_before_init() -> None:
    assert not is_initialized()


def test_is_initialized_true_after_init() -> None:
    cfg = TelemetryConfig(enabled=False)
    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()

    assert is_initialized()


def test_reset_registry_clears_initialized() -> None:
    cfg = TelemetryConfig(enabled=False)
    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()

    assert is_initialized()
    reset_registry()
    assert not is_initialized()


def test_init_telemetry_enabled_creates_real_metrics() -> None:
    cfg = TelemetryConfig(enabled=True)
    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()

    from sase.telemetry import metrics as m

    # Real Counter objects have a _name attribute (prometheus_client strips _total)
    assert hasattr(m.AGENT_RUNS, "_name")
    assert m.AGENT_RUNS._name == "sase_agent_runs"
    assert not isinstance(m.AGENT_RUNS, StubCounter)


def test_init_telemetry_enabled_with_http_server() -> None:
    cfg = TelemetryConfig(enabled=True, exposition_port=19464)
    with (
        patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg),
        patch("sase.telemetry._registry._start_http_server") as mock_server,
    ):
        init_telemetry(start_http_server=True)

    mock_server.assert_called_once_with(19464)
