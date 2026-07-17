"""Tests for telemetry registry management."""

from unittest.mock import patch

from sase.telemetry._accumulators import Counter
from sase.telemetry._config import _TelemetryConfig
from sase.telemetry._registry import init_telemetry
from sase.telemetry._stubs import StubCounter
from tests.telemetry.conftest import (
    is_initialized,
    reset_registry,
    reset_telemetry_config,
)


def setup_function() -> None:
    reset_registry()
    reset_telemetry_config()


def teardown_function() -> None:
    reset_registry()
    reset_telemetry_config()


def test_init_telemetry_disabled_keeps_stubs() -> None:
    cfg = _TelemetryConfig(enabled=False)
    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()

    from sase.telemetry import metrics as m

    assert isinstance(m.AGENT_RUNS, StubCounter)


def test_init_telemetry_is_idempotent() -> None:
    cfg = _TelemetryConfig(enabled=False)
    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()
        init_telemetry()  # second call is a no-op

    assert is_initialized()


def test_is_initialized_false_before_init() -> None:
    assert not is_initialized()


def test_is_initialized_true_after_init() -> None:
    cfg = _TelemetryConfig(enabled=False)
    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()

    assert is_initialized()


def test_reset_registry_clears_initialized() -> None:
    cfg = _TelemetryConfig(enabled=False)
    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()

    assert is_initialized()
    reset_registry()
    assert not is_initialized()


def test_init_telemetry_enabled_creates_real_metrics() -> None:
    cfg = _TelemetryConfig(enabled=True)
    with patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg):
        init_telemetry()

    from sase.telemetry import metrics as m

    assert isinstance(m.AGENT_RUNS, Counter)
    assert m.AGENT_RUNS.name == "sase_agent_runs_total"
    assert not isinstance(m.AGENT_RUNS, StubCounter)


def test_init_telemetry_enabled_with_flusher() -> None:
    cfg = _TelemetryConfig(enabled=True)
    with (
        patch("sase.telemetry._registry.get_telemetry_config", return_value=cfg),
        patch("sase.telemetry._registry._start_flusher") as mock_flusher,
    ):
        init_telemetry(start_flusher=True, source="test-daemon")

    mock_flusher.assert_called_once_with()
