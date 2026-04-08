"""Shared test helpers for telemetry tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from prometheus_client import CollectorRegistry

from sase.telemetry._config import _TelemetryConfig
from sase.telemetry._registry import init_telemetry
from sase.telemetry import metrics as m
from sase.telemetry._stubs import StubCounter, StubGauge, StubHistogram
from sase.telemetry.metrics import METRIC_DEFS

_ENABLED_CFG = _TelemetryConfig(enabled=True)
_DISABLED_CFG = _TelemetryConfig(enabled=False)


def reset_telemetry_config() -> None:
    """Clear the cached telemetry config."""
    import sase.telemetry._config as cfg_mod

    cfg_mod._cached_config = None


def reset_registry() -> None:
    """Reset telemetry registry state and restore stubs."""
    import sase.telemetry._registry as reg_mod

    reg_mod._initialized = False
    reg_mod._registry = None

    stub_factory = {
        "counter": StubCounter,
        "gauge": StubGauge,
        "histogram": StubHistogram,
    }
    for attr, kind, *_ in METRIC_DEFS:
        setattr(m, attr, stub_factory[kind]())


def is_initialized() -> bool:
    """Return whether init_telemetry() has been called."""
    import sase.telemetry._registry as reg_mod

    return reg_mod._initialized


def get_registry():  # noqa: ANN201
    """Return the dedicated CollectorRegistry, or None."""
    import sase.telemetry._registry as reg_mod

    return reg_mod._registry


@pytest.fixture(autouse=True)
def _reset_telemetry():
    """Reset telemetry state before and after every test."""
    reset_registry()
    reset_telemetry_config()
    yield
    reset_registry()
    reset_telemetry_config()


def init_enabled() -> CollectorRegistry:
    """Initialize telemetry in enabled mode and return the registry."""
    with patch(
        "sase.telemetry._registry.get_telemetry_config", return_value=_ENABLED_CFG
    ):
        init_telemetry()
    reg = get_registry()
    assert reg is not None
    return reg


def init_disabled() -> None:
    """Initialize telemetry in disabled mode."""
    with patch(
        "sase.telemetry._registry.get_telemetry_config", return_value=_DISABLED_CFG
    ):
        init_telemetry()


def sample(
    reg: CollectorRegistry, name: str, labels: dict[str, str] | None = None
) -> float | None:
    """Read a sample value from the registry."""
    return reg.get_sample_value(name, labels or {})
