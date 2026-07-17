"""Thin Python adapter for the Rust telemetry store query bindings.

The Rust core owns storage and aggregation semantics.  This module only adds
SASE configuration defaults and catalog-aware helpers shared by CLI and TUI
presentation code.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sase.telemetry._config import get_telemetry_config
from sase.telemetry.catalog import get_catalog

RANGE_SECONDS: dict[str, int] = {
    "15m": 15 * 60,
    "1h": 60 * 60,
    "6h": 6 * 60 * 60,
    "24h": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
}

STEP_SECONDS: dict[str, int] = {
    "15m": 15,
    "1h": 60,
    "6h": 5 * 60,
    "24h": 15 * 60,
    "7d": 60 * 60,
}


def query_instant(
    metric: str,
    *,
    kind: str | None = None,
    filters: dict[str, str] | None = None,
    group_by: Sequence[str] | None = None,
    aggregation: str | None = None,
    quantile: float | None = None,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Query current values for one metric from the configured local store."""
    from sase_core_rs import telemetry_query_instant  # type: ignore[import-untyped]

    config = get_telemetry_config()
    request: dict[str, Any] = {
        "metric": metric,
        "filters": filters or {},
        "staleness_seconds": max(1, int(config.flush_interval_seconds * 2)),
    }
    if kind is not None:
        request["kind"] = kind
    if group_by is not None:
        request["group_by"] = list(group_by)
    if aggregation is not None:
        request["aggregation"] = aggregation
    if quantile is not None:
        request["quantile"] = quantile
    if now_ts is not None:
        request["now_ts"] = now_ts
    return telemetry_query_instant(
        str(config.resolved_store_path), request, config.busy_timeout_ms
    )


def query_range(
    metric: str,
    *,
    start_ts: int,
    end_ts: int,
    step_seconds: int,
    kind: str | None = None,
    filters: dict[str, str] | None = None,
    group_by: Sequence[str] | None = None,
    aggregation: str | None = None,
    quantile: float | None = None,
) -> dict[str, Any]:
    """Query time-bucketed series for one metric from the local store."""
    from sase_core_rs import telemetry_query_range  # type: ignore[import-untyped]

    config = get_telemetry_config()
    request: dict[str, Any] = {
        "metric": metric,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "step_seconds": max(1, step_seconds),
        "filters": filters or {},
    }
    if kind is not None:
        request["kind"] = kind
    if group_by is not None:
        request["group_by"] = list(group_by)
    if aggregation is not None:
        request["aggregation"] = aggregation
    if quantile is not None:
        request["quantile"] = quantile
    return telemetry_query_range(
        str(config.resolved_store_path), request, config.busy_timeout_ms
    )


def store_stats() -> dict[str, Any]:
    """Return configured local-store size, counts, and write freshness."""
    from sase_core_rs import telemetry_store_stats  # type: ignore[import-untyped]

    config = get_telemetry_config()
    return telemetry_store_stats(
        str(config.resolved_store_path), config.busy_timeout_ms
    )


def query_snapshot(*, now_ts: int | None = None) -> list[dict[str, Any]]:
    """Return every current catalog value in a stable, presentation-ready shape."""
    samples: list[dict[str, Any]] = []
    for info in get_catalog():
        result = query_instant(
            info.prometheus_name,
            kind=info.kind,
            now_ts=now_ts,
        )
        for value in result.get("values", []):
            samples.append(
                {
                    **value,
                    "metric": info.prometheus_name,
                    "kind": info.kind,
                    "subsystem": info.subsystem,
                    "aggregation": result.get("aggregation", ""),
                }
            )
    return sorted(
        samples,
        key=lambda item: (
            str(item["subsystem"]),
            str(item["metric"]),
            sorted(dict(item.get("labels", {})).items()),
        ),
    )


def resolve_metric(name: str) -> tuple[str, str] | None:
    """Resolve a catalog metric by wire name or Python attribute name."""
    normalized = name.lower()
    for info in get_catalog():
        if normalized in {info.prometheus_name.lower(), info.attr.lower()}:
            return info.prometheus_name, info.kind
    return None


def parse_group_by(value: str | None) -> list[str]:
    """Parse a comma-separated group-by value into stable unique labels."""
    if not value:
        return []
    labels: list[str] = []
    for raw in value.split(","):
        label = raw.strip()
        if label and label not in labels:
            labels.append(label)
    return labels


__all__ = [
    "RANGE_SECONDS",
    "STEP_SECONDS",
    "parse_group_by",
    "query_instant",
    "query_range",
    "query_snapshot",
    "resolve_metric",
    "store_stats",
]
