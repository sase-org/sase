"""Telemetry configuration loaded from the merged sase config."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_cached_config: _TelemetryConfig | None = None


@dataclass(frozen=True)
class HealthThresholds:
    """Thresholds for the ``sase telemetry health`` traffic-light check."""

    error_rate_warn: float = 10.0
    error_rate_critical: float = 25.0
    retry_rate_warn: float = 10.0
    retry_rate_critical: float = 25.0
    p95_latency_warn: float = 300.0
    p95_latency_critical: float = 600.0


@dataclass(frozen=True)
class _TelemetryConfig:
    """Prometheus telemetry settings."""

    enabled: bool = False
    exposition_port: int = 9464
    pushgateway_url: str = "localhost:9091"
    health_thresholds: HealthThresholds = HealthThresholds()


def get_telemetry_config() -> _TelemetryConfig:
    """Return the telemetry config, loading and caching on first call."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    _cached_config = _load_telemetry_config()
    return _cached_config


def _load_telemetry_config() -> _TelemetryConfig:
    """Load telemetry settings from the merged sase config."""
    from sase.config.core import load_merged_config

    merged = load_merged_config()
    section: dict[str, Any] = merged.get("telemetry", {})
    if not isinstance(section, dict):
        return _TelemetryConfig()

    prom: dict[str, Any] = section.get("prometheus", {})
    if not isinstance(prom, dict):
        prom = {}

    ht_raw: dict[str, Any] = section.get("health_thresholds", {})
    if not isinstance(ht_raw, dict):
        ht_raw = {}
    ht = HealthThresholds(
        error_rate_warn=float(ht_raw.get("error_rate_warn", 10.0)),
        error_rate_critical=float(ht_raw.get("error_rate_critical", 25.0)),
        retry_rate_warn=float(ht_raw.get("retry_rate_warn", 10.0)),
        retry_rate_critical=float(ht_raw.get("retry_rate_critical", 25.0)),
        p95_latency_warn=float(ht_raw.get("p95_latency_warn", 300.0)),
        p95_latency_critical=float(ht_raw.get("p95_latency_critical", 600.0)),
    )

    return _TelemetryConfig(
        enabled=bool(section.get("enabled", False)),
        exposition_port=int(prom.get("exposition_port", 9464)),
        pushgateway_url=str(prom.get("pushgateway_url", "localhost:9091")),
        health_thresholds=ht,
    )
