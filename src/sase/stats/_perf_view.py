"""Immutable, I/O-free presentation models for the Statistics Perf view."""

from __future__ import annotations

from sase.stats._perf_view_coverage import build_coverage
from sase.stats._perf_view_latency import build_latency
from sase.stats._perf_view_sections import (
    STARTUP_CRITICAL_SECONDS,
    STARTUP_WARN_SECONDS,
    build_launches,
    build_stalls,
    build_startup,
)
from sase.stats._view_models import PerfView
from sase.stats._view_payload import Payload, mapping
from sase.stats.perf_query import PerfGroupBy
from sase.stats.ranges import StatsRange
from sase.telemetry._config import HealthThresholds


def build_perf_view(
    perf_payload: Payload,
    telemetry_payload: Payload,
    *,
    selected_range: StatsRange,
    previous_perf_payload: Payload | None = None,
    previous_telemetry_payload: Payload | None = None,
    group_by: PerfGroupBy = "subsystem",
    now: float | None = None,
    health_thresholds: HealthThresholds | None = None,
) -> PerfView:
    """Build the Perf view without performing I/O."""
    resolved_group: PerfGroupBy = (
        group_by if group_by in {"subsystem", "provider", "workflow"} else "subsystem"
    )
    thresholds = (
        health_thresholds if health_thresholds is not None else HealthThresholds()
    )
    previous_perf = mapping(previous_perf_payload)
    previous_telemetry = mapping(previous_telemetry_payload)

    startup = build_startup(
        mapping(perf_payload.get("startup")),
        mapping(previous_perf.get("startup")),
    )
    stalls = build_stalls(mapping(perf_payload.get("stalls")))
    launches = build_launches(mapping(perf_payload.get("launches")))
    latency = build_latency(
        telemetry_payload,
        previous_telemetry,
        group_by=resolved_group,
        thresholds=thresholds,
    )
    coverage = build_coverage(
        perf_payload,
        telemetry_payload,
        selected_range=selected_range,
        now=now,
    )
    tiles = (
        startup.tile,
        stalls.tile,
        launches.tile,
        latency.agent_tile,
        latency.llm_tile,
    )
    available = (
        startup.available
        or stalls.available
        or launches.available
        or latency.available
        or not coverage.telemetry.enabled
        or any(entry.present for entry in coverage.logs)
    )
    return PerfView(
        available=available,
        selected_range=selected_range,
        group_by=resolved_group,
        startup=startup,
        stalls=stalls,
        launches=launches,
        latency=latency,
        coverage=coverage,
        tiles=tiles,
    )


__all__ = [
    "STARTUP_CRITICAL_SECONDS",
    "STARTUP_WARN_SECONDS",
    "PerfView",
    "build_perf_view",
]
