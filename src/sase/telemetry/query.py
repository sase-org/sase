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


def _query_instant(
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
        result = _query_instant(
            info.metric_name,
            kind=info.kind,
            now_ts=now_ts,
        )
        for value in result.get("values", []):
            samples.append(
                {
                    **value,
                    "metric": info.metric_name,
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


__all__ = [
    "query_range",
    "query_snapshot",
    "store_stats",
]
