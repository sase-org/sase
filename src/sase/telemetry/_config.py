"""Telemetry configuration loaded from the merged sase config."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

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
class _RetentionConfig:
    """Retention windows passed to the Rust telemetry store."""

    raw_seconds: int = 48 * 60 * 60
    rollup_5m_seconds: int = 30 * 24 * 60 * 60
    rollup_1h_seconds: int = 365 * 24 * 60 * 60

    def as_wire(self) -> dict[str, int]:
        """Return the core binding's retention wire shape."""
        return {
            "raw_seconds": self.raw_seconds,
            "rollup_5m_seconds": self.rollup_5m_seconds,
            "rollup_1h_seconds": self.rollup_1h_seconds,
        }


def _default_telemetry_store_path() -> Path:
    """Return the default local telemetry database path."""
    return sase_home() / "telemetry" / "metrics.sqlite"


@dataclass(frozen=True)
class _TelemetryConfig:
    """Local telemetry settings."""

    enabled: bool = True
    flush_interval_seconds: float = 15.0
    retention: _RetentionConfig = _RetentionConfig()
    store_path: Path | None = None
    busy_timeout_ms: int = 250
    health_thresholds: HealthThresholds = HealthThresholds()

    @property
    def resolved_store_path(self) -> Path:
        """Resolve the store lazily so ``SASE_HOME`` redirection is honored."""
        return self.store_path or _default_telemetry_store_path()


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

    retention_raw: dict[str, Any] = section.get("retention", {})
    if not isinstance(retention_raw, dict):
        retention_raw = {}
    retention = _RetentionConfig(
        raw_seconds=int(retention_raw.get("raw_seconds", 48 * 60 * 60)),
        rollup_5m_seconds=int(
            retention_raw.get("rollup_5m_seconds", 30 * 24 * 60 * 60)
        ),
        rollup_1h_seconds=int(
            retention_raw.get("rollup_1h_seconds", 365 * 24 * 60 * 60)
        ),
    )

    return _TelemetryConfig(
        enabled=bool(section.get("enabled", True)),
        flush_interval_seconds=float(section.get("flush_interval_seconds", 15.0)),
        retention=retention,
        health_thresholds=ht,
    )
