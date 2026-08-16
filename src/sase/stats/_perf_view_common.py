"""Shared calculations for Statistics Perf view presentation models."""

from __future__ import annotations

from sase.telemetry._config import HealthThresholds
from sase.telemetry.render.palette import Status

_STATUS_RANK: dict[Status, int] = {"ok": 0, "warning": 1, "critical": 2}


def delta_ratio(current: float | None, previous: float | None) -> float | None:
    """Return the relative change from ``previous`` to ``current``."""
    if current is None or previous is None:
        return None
    if previous == 0:
        return 0.0 if current == 0 else None
    return (current - previous) / previous


def percent(numerator: float, denominator: float) -> float | None:
    """Return ``numerator`` as a percentage of a positive denominator."""
    if denominator <= 0:
        return None
    return numerator / denominator * 100.0


def share(numerator: float, denominator: float) -> float:
    """Return a ratio, treating an empty denominator as an empty share."""
    return float(numerator) / float(denominator) if denominator else 0.0


def latency_status(
    p95: float | None,
    error_rate: float | None,
    thresholds: HealthThresholds,
    *,
    retry_rate: float | None = None,
) -> Status | None:
    """Combine latency, error, and retry health into one status."""
    statuses: list[Status] = []
    if p95 is not None:
        statuses.append(
            _threshold_status(
                p95, thresholds.p95_latency_warn, thresholds.p95_latency_critical
            )
        )
    if error_rate is not None:
        statuses.append(
            _threshold_status(
                error_rate, thresholds.error_rate_warn, thresholds.error_rate_critical
            )
        )
    if retry_rate is not None:
        statuses.append(
            _threshold_status(
                retry_rate, thresholds.retry_rate_warn, thresholds.retry_rate_critical
            )
        )
    return _worst(*statuses)


def _threshold_status(value: float, warn: float, critical: float) -> Status:
    if value >= critical:
        return "critical"
    if value >= warn:
        return "warning"
    return "ok"


def _worst(*statuses: Status | None) -> Status | None:
    present = [status for status in statuses if status is not None]
    if not present:
        return None
    return max(present, key=lambda status: _STATUS_RANK[status])
