"""Immutable, I/O-free presentation models for the Statistics Perf view."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from sase.stats._view_models import (
    PerfCoverage,
    PerfHeroTile,
    PerfLatencyRow,
    PerfLatencySection,
    PerfLaunchStage,
    PerfLaunchesSection,
    PerfLogCoverage,
    PerfProbeStatus,
    PerfSlowestSession,
    PerfStallContextRow,
    PerfStallEventRow,
    PerfStallsSection,
    PerfStartupSection,
    PerfStartupStageRow,
    PerfTelemetryCoverage,
    PerfView,
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
from sase.stats.perf_query import PerfGroupBy
from sase.stats.ranges import StatsRange
from sase.telemetry._config import HealthThresholds
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
_SUBSYSTEM_ROWS: tuple[
    tuple[str, str, str, str | None, str | None, str | None], ...
] = (
    (
        "agent",
        "Agent runs",
        "sase_agent_run_duration_seconds",
        "sase_agent_runs_total",
        "sase_agent_runs_total:error",
        None,
    ),
    (
        "llm",
        "LLM calls",
        "sase_llm_invocation_duration_seconds",
        "sase_llm_invocations_total",
        "sase_llm_errors_total",
        "sase_llm_retries_total",
    ),
    (
        "hooks",
        "Hooks",
        "sase_hook_duration_seconds",
        "sase_hook_executions_total",
        None,
        "sase_hook_retries_total",
    ),
    (
        "workflows",
        "Workflows",
        "sase_workflow_duration_seconds",
        None,
        None,
        None,
    ),
    (
        "axe",
        "Axe cycles",
        "sase_axe_cycle_duration_seconds",
        None,
        None,
        None,
    ),
)
_PERF_PROBES: tuple[tuple[str, str], ...] = (
    ("SASE_TUI_PERF", "Set SASE_TUI_PERF=1 to record per-keystroke j/k timings."),
    ("SASE_TUI_TRACE", "Set SASE_TUI_TRACE=1 to record hot-path span traces."),
)
_STATUS_RANK: dict[Status, int] = {"ok": 0, "warning": 1, "critical": 2}
_PendingLatency = tuple[
    str,
    str,
    float | None,
    float | None,
    float | None,
    int,
    float | None,
    float | None,
]


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

    startup = _build_startup(
        mapping(perf_payload.get("startup")),
        mapping(previous_perf.get("startup")),
    )
    stalls = _build_stalls(mapping(perf_payload.get("stalls")))
    launches = _build_launches(mapping(perf_payload.get("launches")))
    latency = _build_latency(
        telemetry_payload,
        previous_telemetry,
        group_by=resolved_group,
        thresholds=thresholds,
    )
    coverage = _build_coverage(
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


def _build_startup(startup: Payload, previous: Payload) -> PerfStartupSection:
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
        delta_ratio=_delta_ratio(median, previous_median) if available else None,
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


def _build_stalls(stalls: Payload) -> PerfStallsSection:
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


def _build_launches(launches: Payload) -> PerfLaunchesSection:
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


def _build_latency(
    telemetry: Payload,
    previous: Payload,
    *,
    group_by: PerfGroupBy,
    thresholds: HealthThresholds,
) -> PerfLatencySection:
    enabled = boolean(telemetry.get("enabled"))
    if group_by == "provider":
        built_rows = _provider_rows(telemetry, thresholds)
    elif group_by == "workflow":
        built_rows = _workflow_rows(telemetry, thresholds)
    else:
        built_rows = _subsystem_rows(telemetry, thresholds)
    available = enabled and any(
        row.count > 0 or row.p95 is not None or row.p50 is not None
        for row in built_rows
    )
    agent_p95, agent_count = _agent_headline(telemetry)
    previous_agent_p95, _ = _agent_headline(previous)
    llm_p95, llm_count, llm_error_rate, llm_retry_rate = _llm_headline(telemetry)
    agent_error_rate = _agent_error_rate(telemetry)
    agent_tile = PerfHeroTile(
        key="agent_p95",
        caption="Agent p95",
        available=enabled and (agent_p95 is not None or agent_count > 0),
        value=agent_p95 if enabled else None,
        status=_latency_status(agent_p95, agent_error_rate, thresholds)
        if enabled and (agent_p95 is not None or agent_error_rate is not None)
        else None,
        delta_ratio=_delta_ratio(agent_p95, previous_agent_p95) if enabled else None,
        lower_is_better=True,
        sparkline=(),
        detail=f"{agent_count} runs",
        sample_count=agent_count,
    )
    llm_tile = PerfHeroTile(
        key="llm_p95",
        caption="LLM p95",
        available=enabled and (llm_p95 is not None or llm_count > 0),
        value=llm_p95 if enabled else None,
        status=_latency_status(llm_p95, llm_error_rate, thresholds)
        if enabled and (llm_p95 is not None or llm_error_rate is not None)
        else None,
        delta_ratio=None,
        lower_is_better=True,
        sparkline=(),
        detail=_llm_detail(llm_error_rate, llm_retry_rate),
        sample_count=llm_count,
    )
    if not enabled:
        agent_tile = _unavailable_tile(agent_tile)
        llm_tile = _unavailable_tile(llm_tile)
        built_rows = ()
        available = False
    return PerfLatencySection(
        available=available,
        group_by=group_by,
        rows=built_rows,
        agent_tile=agent_tile,
        llm_tile=llm_tile,
    )


def _unavailable_tile(tile: PerfHeroTile) -> PerfHeroTile:
    return PerfHeroTile(
        key=tile.key,
        caption=tile.caption,
        available=False,
        value=None,
        status=None,
        delta_ratio=None,
        lower_is_better=tile.lower_is_better,
        sparkline=(),
        detail=tile.detail,
        sample_count=0,
    )


def _subsystem_rows(
    telemetry: Payload, thresholds: HealthThresholds
) -> tuple[PerfLatencyRow, ...]:
    built: list[PerfLatencyRow] = []
    counts: list[int] = []
    pending: list[_PendingLatency] = []
    for key, label, hist, count_key, error_key, retry_key in _SUBSYSTEM_ROWS:
        p50, p95, maximum = _histogram_values(telemetry, hist)
        count = int(_counter_value(telemetry, count_key)) if count_key else 0
        errors = _counter_value(telemetry, error_key) if error_key else 0.0
        retries = _counter_value(telemetry, retry_key) if retry_key else 0.0
        error_rate = _percent(errors, count) if error_key else None
        retry_rate = _percent(retries, count) if retry_key else None
        pending.append((key, label, p50, p95, maximum, count, error_rate, retry_rate))
        counts.append(count)
    total = sum(counts)
    for key, label, p50, p95, maximum, count, error_rate, retry_rate in pending:
        built.append(
            PerfLatencyRow(
                key=key,
                label=label,
                p50=p50,
                p95=p95,
                max=maximum,
                count=count,
                error_rate=error_rate,
                retry_rate=retry_rate,
                share=_share(count, total),
                tokens_in=None,
                tokens_out=None,
                cache_read_tokens=None,
                cache_read_share=None,
                status=_latency_status(
                    p95, error_rate, thresholds, retry_rate=retry_rate
                ),
            )
        )
    return tuple(built)


def _provider_rows(
    telemetry: Payload, thresholds: HealthThresholds
) -> tuple[PerfLatencyRow, ...]:
    llm_p50 = _hist_by(
        "sase_llm_invocation_duration_seconds", "p50", "provider", telemetry
    )
    llm_p95 = _hist_by(
        "sase_llm_invocation_duration_seconds", "p95", "provider", telemetry
    )
    llm_max = _hist_by(
        "sase_llm_invocation_duration_seconds", "max", "provider", telemetry
    )
    agent_p50 = _hist_by(
        "sase_agent_run_duration_seconds", "p50", "llm_provider", telemetry
    )
    agent_p95 = _hist_by(
        "sase_agent_run_duration_seconds", "p95", "llm_provider", telemetry
    )
    agent_max = _hist_by(
        "sase_agent_run_duration_seconds", "max", "llm_provider", telemetry
    )
    invocations = _count_by("sase_llm_invocations_total", "provider", telemetry)
    errors = _count_by("sase_llm_errors_total", "provider", telemetry)
    retries = _count_by("sase_llm_retries_total", "provider", telemetry)
    runs = _count_by("sase_agent_runs_total", "llm_provider", telemetry)
    tokens_in = _count_by("sase_llm_input_tokens_total", "provider", telemetry)
    tokens_out = _count_by("sase_llm_output_tokens_total", "provider", telemetry)
    cache_read = _count_by("sase_llm_cache_read_tokens_total", "provider", telemetry)
    names = sorted(
        {
            *llm_p95,
            *agent_p95,
            *invocations,
            *runs,
            *tokens_in,
            *tokens_out,
            *cache_read,
        }
    )
    built: list[PerfLatencyRow] = []
    counts = [int(invocations.get(name, runs.get(name, 0.0))) for name in names]
    total = sum(counts)
    for name, count in zip(names, counts, strict=True):
        p50 = llm_p50.get(name, agent_p50.get(name))
        p95 = llm_p95.get(name, agent_p95.get(name))
        maximum = llm_max.get(name, agent_max.get(name))
        denom = invocations.get(name, 0.0)
        error_rate = _percent(errors.get(name, 0.0), denom)
        retry_rate = _percent(retries.get(name, 0.0), denom)
        in_tokens = int(tokens_in.get(name, 0.0))
        out_tokens = int(tokens_out.get(name, 0.0))
        cache_tokens = int(cache_read.get(name, 0.0))
        built.append(
            PerfLatencyRow(
                key=name,
                label=name,
                p50=p50,
                p95=p95,
                max=maximum,
                count=count,
                error_rate=error_rate,
                retry_rate=retry_rate,
                share=_share(count, total),
                tokens_in=in_tokens,
                tokens_out=out_tokens,
                cache_read_tokens=cache_tokens,
                cache_read_share=_share(cache_tokens, in_tokens + cache_tokens),
                status=_latency_status(
                    p95, error_rate, thresholds, retry_rate=retry_rate
                ),
            )
        )
    built.sort(key=lambda row: (-row.count, row.label.casefold()))
    return tuple(built)


def _workflow_rows(
    telemetry: Payload, thresholds: HealthThresholds
) -> tuple[PerfLatencyRow, ...]:
    agent_p50 = _hist_by(
        "sase_agent_run_duration_seconds", "p50", "workflow", telemetry
    )
    agent_p95 = _hist_by(
        "sase_agent_run_duration_seconds", "p95", "workflow", telemetry
    )
    agent_max = _hist_by(
        "sase_agent_run_duration_seconds", "max", "workflow", telemetry
    )
    flow_p50 = _hist_by("sase_workflow_duration_seconds", "p50", "workflow", telemetry)
    flow_p95 = _hist_by("sase_workflow_duration_seconds", "p95", "workflow", telemetry)
    flow_max = _hist_by("sase_workflow_duration_seconds", "max", "workflow", telemetry)
    runs = _count_by("sase_agent_runs_total", "workflow", telemetry)
    errors = _count_by("sase_agent_runs_total:error", "workflow", telemetry)
    names = sorted({*agent_p95, *flow_p95, *runs})
    counts = [int(runs.get(name, 0.0)) for name in names]
    total = sum(counts)
    built: list[PerfLatencyRow] = []
    for name, count in zip(names, counts, strict=True):
        p95 = agent_p95.get(name, flow_p95.get(name))
        error_rate = _percent(errors.get(name, 0.0), float(count))
        built.append(
            PerfLatencyRow(
                key=name,
                label=name,
                p50=agent_p50.get(name, flow_p50.get(name)),
                p95=p95,
                max=agent_max.get(name, flow_max.get(name)),
                count=count,
                error_rate=error_rate,
                retry_rate=None,
                share=_share(count, total),
                tokens_in=None,
                tokens_out=None,
                cache_read_tokens=None,
                cache_read_share=None,
                status=_latency_status(p95, error_rate, thresholds),
            )
        )
    built.sort(key=lambda row: (-row.count, row.label.casefold()))
    return tuple(built)


def _agent_headline(telemetry: Payload) -> tuple[float | None, int]:
    _, p95, _ = _histogram_values(telemetry, "sase_agent_run_duration_seconds")
    count = int(_counter_value(telemetry, "sase_agent_runs_total"))
    return p95, count


def _agent_error_rate(telemetry: Payload) -> float | None:
    total = _counter_value(telemetry, "sase_agent_runs_total")
    errors = _counter_value(telemetry, "sase_agent_runs_total:error")
    return _percent(errors, total)


def _llm_headline(
    telemetry: Payload,
) -> tuple[float | None, int, float | None, float | None]:
    _, p95, _ = _histogram_values(telemetry, "sase_llm_invocation_duration_seconds")
    count = _counter_value(telemetry, "sase_llm_invocations_total")
    errors = _counter_value(telemetry, "sase_llm_errors_total")
    retries = _counter_value(telemetry, "sase_llm_retries_total")
    return p95, int(count), _percent(errors, count), _percent(retries, count)


def _llm_detail(error_rate: float | None, retry_rate: float | None) -> str:
    err = 0.0 if error_rate is None else error_rate
    retry = 0.0 if retry_rate is None else retry_rate
    return f"err {err:.0f}% · retry {retry:.0f}%"


def _histogram_values(
    telemetry: Payload, metric: str
) -> tuple[float | None, float | None, float | None]:
    entry = mapping(mapping(telemetry.get("histograms")).get(metric))
    return (
        _first_series_value(mapping(entry.get("p50"))),
        _first_series_value(mapping(entry.get("p95"))),
        _first_series_value(mapping(entry.get("max"))),
    )


def _counter_value(telemetry: Payload, key: str) -> float:
    entry = mapping(mapping(telemetry.get("counters")).get(key))
    return _first_series_value(entry) or 0.0


def _first_series_value(entry: Payload) -> float | None:
    series = entry.get("series")
    if not isinstance(series, (list, tuple)) or not series:
        return None
    first = series[0]
    if not isinstance(first, Mapping):
        return None
    return optional_number(first.get("value"))


def _hist_by(
    metric: str, agg: str, label_key: str, telemetry: Payload
) -> dict[str, float]:
    return _labeled_values(telemetry, "histograms", metric, agg, label_key)


def _count_by(metric: str, label_key: str, telemetry: Payload) -> dict[str, float]:
    return _labeled_values(telemetry, "counters", metric, None, label_key)


def _labeled_values(
    telemetry: Payload,
    section: Literal["histograms", "counters"],
    metric: str,
    agg: str | None,
    label_key: str,
) -> dict[str, float]:
    root = mapping(telemetry.get(section))
    entry = mapping(root.get(metric))
    payload = mapping(entry.get(agg)) if agg is not None else entry
    values: dict[str, float] = {}
    series = payload.get("series")
    if not isinstance(series, (list, tuple)):
        return values
    for item in series:
        if not isinstance(item, Mapping):
            continue
        value = optional_number(item.get("value"))
        if value is None:
            continue
        labels = mapping(item.get("labels"))
        values[text(labels.get(label_key), "unknown")] = value
    return values


def _build_coverage(
    perf_payload: Payload,
    telemetry_payload: Payload,
    *,
    selected_range: StatsRange,
    now: float | None,
) -> PerfCoverage:
    logs = tuple(
        PerfLogCoverage(
            source=text(row.get("source"), "unknown"),
            path=text(row.get("path")),
            present=boolean(row.get("present")),
            records_scanned=integer(row.get("records_scanned")),
            records_in_window=integer(row.get("records_in_window")),
            earliest_ts=optional_number(row.get("earliest_ts")),
            latest_ts=optional_number(row.get("latest_ts")),
            truncated=boolean(row.get("truncated")),
            malformed_skipped=integer(row.get("malformed_skipped")),
        )
        for row in rows(perf_payload, "coverage")
    )
    store = mapping(telemetry_payload.get("store"))
    last_write_ts = _optional_int(store.get("last_write_ts"))
    last_write_age = None
    if now is not None and last_write_ts is not None:
        last_write_age = max(0.0, float(now) - float(last_write_ts))
    enabled = boolean(telemetry_payload.get("enabled"))
    telemetry = PerfTelemetryCoverage(
        enabled=enabled,
        available=enabled and _telemetry_has_samples(store, telemetry_payload),
        store_path=text(store.get("store_path")),
        store_size_bytes=integer(store.get("db_size_bytes")),
        raw_sample_count=integer(store.get("raw_sample_count")),
        rollup_5m_count=integer(store.get("rollup_5m_count")),
        rollup_1h_count=integer(store.get("rollup_1h_count")),
        resolution=text(telemetry_payload.get("resolution")) or None,
        last_write_ts=last_write_ts,
        last_write_age_seconds=last_write_age,
        last_write_by_subsystem=_subsystem_writes(store.get("last_write_by_subsystem")),
        earliest_sample_ts=_optional_int(store.get("earliest_sample_ts")),
        latest_sample_ts=_optional_int(store.get("latest_sample_ts")),
        error=text(telemetry_payload.get("error")) or None,
    )
    probes = tuple(
        PerfProbeStatus(name=name, enabled=name in os.environ, hint=hint)
        for name, hint in _PERF_PROBES
    )
    notes = _coverage_notes(logs, telemetry, selected_range)
    return PerfCoverage(
        telemetry=telemetry,
        logs=logs,
        probes=probes,
        notes=notes,
    )


def _telemetry_has_samples(store: Payload, telemetry: Payload) -> bool:
    has_store_rows = any(
        integer(store.get(key))
        for key in ("raw_sample_count", "rollup_5m_count", "rollup_1h_count")
    )
    if has_store_rows:
        return True
    histograms = mapping(telemetry.get("histograms"))
    counters = mapping(telemetry.get("counters"))
    return bool(histograms) or bool(counters)


def _subsystem_writes(value: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, Mapping):
        return ()
    writes: list[tuple[str, int]] = []
    for key, raw in value.items():
        if not isinstance(key, str):
            continue
        stamp = _optional_int(raw)
        if stamp is None:
            continue
        writes.append((key, stamp))
    writes.sort(key=lambda item: item[0])
    return tuple(writes)


def _coverage_notes(
    logs: tuple[PerfLogCoverage, ...],
    telemetry: PerfTelemetryCoverage,
    selected_range: StatsRange,
) -> tuple[str, ...]:
    notes: list[str] = []
    malformed = sum(entry.malformed_skipped for entry in logs)
    if malformed:
        notes.append(f"{malformed} unreadable records skipped")
    truncated = [entry.source for entry in logs if entry.truncated]
    if truncated:
        notes.append(
            "Bounded log read truncated older records for: " + ", ".join(truncated)
        )
    if not telemetry.enabled:
        notes.append("Telemetry is disabled (telemetry.enabled).")
    elif telemetry.error:
        notes.append(f"Telemetry store error: {telemetry.error}")
    if selected_range.start_ts == 0:
        notes.append(
            "All time means as far back as retained telemetry and bounded logs go."
        )
    return tuple(notes)


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


def _latency_status(
    p95: float | None,
    error_rate: float | None,
    thresholds: HealthThresholds,
    *,
    retry_rate: float | None = None,
) -> Status | None:
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


def _delta_ratio(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        return 0.0 if current == 0 else None
    return (current - previous) / previous


def _percent(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator * 100.0


def _share(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


__all__ = [
    "STARTUP_CRITICAL_SECONDS",
    "STARTUP_WARN_SECONDS",
    "PerfView",
    "build_perf_view",
]
