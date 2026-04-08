"""Shared test helpers for telemetry tests."""

from __future__ import annotations

from sase.telemetry import metrics as m
from sase.telemetry._stubs import StubCounter, StubGauge, StubHistogram
from sase.telemetry.metrics import METRIC_DEFS


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
