"""Log-backed sections for the Statistics Perf view."""

from __future__ import annotations

from sase.stats._perf_view_common import delta_ratio
from sase.stats._view_models import (
    PerfHeroTile,
    PerfLaunchStage,
    PerfLaunchesSection,
    PerfSlowestSession,
    PerfStallContextRow,
    PerfStallEventRow,
    PerfStallsSection,
    PerfStartupSection,
    PerfStartupStageRow,
)
from sase.stats._view_payload import (
    Payload,
    boolean,
    integer,
    mapping,
    number,
    optional_number,
    rows,
    text,
)
from sase.telemetry.render.palette import Status

STARTUP_WARN_SECONDS = 2.0
STARTUP_CRITICAL_SECONDS = 5.0

_STALL_EVENTS = ("tui_stall", "tui_pump_stall")
_HITCH_EVENTS = ("tui_hitch", "tui_pump_hitch")
_STARTUP_STAGE_LABELS: dict[str, str] = {
    "process_to_mount": "process→mount",
    "mount_to_first_paint": "mount→first paint",
    "visible_ready": "visible ready",
    "all_surfaces_ready": "all surfaces ready",
}


def build_startup(startup: Payload, previous: Payload) -> PerfStartupSection:
    """Build the startup timing section."""
    stages = tuple(_startup_stage_row(row) for row in rows(startup, "stages"))
    visible_ready = next((row for row in stages if row.stage == "visible_ready"), None)
    sparkline = tuple(
        number(point.get("visible_ready_seconds"))
        for point in rows(startup, "visible_ready_series")
    )
    sessions = integer(startup.get("sessions"))
    available = sessions > 0
    median = visible_ready.p50 if visible_ready is not None else None
    previous_median = None
    previous_stages = rows(previous, "stages")
    for row in previous_stages:
        if text(row.get("stage")) == "visible_ready":
            previous_median = optional_number(mapping(row.get("summary")).get("p50"))
            break
    slowest_payload = mapping(startup.get("slowest_session"))
    slowest = None
    if slowest_payload:
        slowest = PerfSlowestSession(
            ts=number(slowest_payload.get("ts")),
            visible_ready_seconds=number(slowest_payload.get("visible_ready_seconds")),
            initial_tab=text(slowest_payload.get("initial_tab")) or None,
        )
    tile = PerfHeroTile(
        key="startup",
        caption="Startup",
        available=available,
        value=median if available else None,
        status=_startup_status(median) if available else None,
        delta_ratio=delta_ratio(median, previous_median) if available else None,
        lower_is_better=True,
        sparkline=sparkline,
        detail=_session_detail(sessions, slowest),
        sample_count=sessions,
    )
    return PerfStartupSection(
        available=available,
        sessions=sessions,
        stages=stages,
        sparkline=sparkline,
        slowest=slowest,
        tile=tile,
    )


def _startup_stage_row(row: Payload) -> PerfStartupStageRow:
    stage_id = text(row.get("stage"), "unknown")
    summary = mapping(row.get("summary"))
    return PerfStartupStageRow(
        stage=stage_id,
        label=_STARTUP_STAGE_LABELS.get(stage_id, stage_id),
        p50=optional_number(summary.get("p50")),
        p95=optional_number(summary.get("p95")),
        max=optional_number(summary.get("max")),
        samples=integer(summary.get("samples")),
    )


def _session_detail(sessions: int, slowest: PerfSlowestSession | None) -> str:
    if sessions <= 0:
        return ""
    if slowest is None:
        return f"{sessions} sessions"
    tab = slowest.initial_tab or "unknown"
    return f"{sessions} sessions · slowest {tab}"


def build_stalls(stalls: Payload) -> PerfStallsSection:
    """Build the TUI stall and hitch section."""
    events = tuple(
        PerfStallEventRow(
            event=text(row.get("event"), "unknown"),
            count=integer(row.get("count")),
            worst_seconds=optional_number(row.get("worst_seconds")),
            median_seconds=optional_number(row.get("median_seconds")),
            last_seen_ts=optional_number(row.get("last_seen_ts")),
            suppressed_count=integer(row.get("suppressed_count")),
        )
        for row in rows(stalls, "events")
    )
    stall_count = sum(row.count for row in events if row.event in _STALL_EVENTS)
    hitch_count = sum(row.count for row in events if row.event in _HITCH_EVENTS)
    worst = max(
        (row.worst_seconds for row in events if row.worst_seconds is not None),
        default=None,
    )
    available = (
        stall_count > 0 or hitch_count > 0 or integer(stalls.get("recovery_count")) > 0
    )
    top_contexts = tuple(
        PerfStallContextRow(text(row.get("name"), "unknown"), integer(row.get("count")))
        for row in rows(stalls, "top_contexts")
    )
    total = stall_count + hitch_count
    detail = f"worst {worst:.1f}s" if worst is not None else ""
    tile = PerfHeroTile(
        key="stalls",
        caption="Stalls",
        available=available,
        value=float(total) if available else None,
        status=_stall_status(stall_count, hitch_count) if available else None,
        delta_ratio=None,
        lower_is_better=True,
        sparkline=(),
        detail=detail,
        sample_count=total,
    )
    return PerfStallsSection(
        available=available,
        stall_count=stall_count,
        hitch_count=hitch_count,
        worst_seconds=worst,
        recovery_count=integer(stalls.get("recovery_count")),
        events=events,
        top_contexts=top_contexts,
        tile=tile,
    )


def build_launches(launches: Payload) -> PerfLaunchesSection:
    """Build the agent launch timing section."""
    summary = mapping(launches.get("total_ms"))
    count = integer(launches.get("count"))
    available = count > 0
    p50 = optional_number(summary.get("p50"))
    p95 = optional_number(summary.get("p95"))
    max_ms = optional_number(summary.get("max"))
    slow_stage_count = integer(launches.get("slow_stage_count"))
    worst_stages = tuple(
        PerfLaunchStage(
            ts=number(row.get("ts")),
            stage=text(row.get("stage"), "unknown"),
            elapsed_ms=number(row.get("elapsed_ms")),
            operation=text(row.get("operation")) or None,
            slow_stage=boolean(row.get("slow_stage")),
        )
        for row in rows(launches, "worst_stages")
    )
    tile = PerfHeroTile(
        key="launch",
        caption="Launch",
        available=available,
        value=p95 if available else None,
        status=None,
        delta_ratio=None,
        lower_is_better=True,
        sparkline=(),
        detail=f"{count} launches · {slow_stage_count} slow stages",
        sample_count=count,
    )
    return PerfLaunchesSection(
        available=available,
        count=count,
        p50_ms=p50,
        p95_ms=p95,
        max_ms=max_ms,
        slow_stage_count=slow_stage_count,
        worst_stages=worst_stages,
        tile=tile,
    )


def _startup_status(median: float | None) -> Status | None:
    if median is None:
        return None
    if median >= STARTUP_CRITICAL_SECONDS:
        return "critical"
    if median >= STARTUP_WARN_SECONDS:
        return "warning"
    return "ok"


def _stall_status(stall_count: int, hitch_count: int) -> Status:
    if stall_count > 0:
        return "critical"
    if hitch_count > 0:
        return "warning"
    return "ok"
