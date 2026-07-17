"""``sase telemetry dashboard`` — live charts from the local metric store."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Any

from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from sase.telemetry._config import get_telemetry_config
from sase.telemetry.query import (
    RANGE_SECONDS,
    STEP_SECONDS,
    query_instant,
    query_range,
    store_stats,
)
from sase.telemetry.render import (
    Series,
    Status,
    ValueFormat,
    render_line_chart,
    render_stat_tile,
)


@dataclass(frozen=True, slots=True)
class _SeriesQuery:
    metric: str
    kind: str
    aggregation: str
    group_by: tuple[str, ...] = ()
    filters: tuple[tuple[str, str], ...] = ()
    quantile: float | None = None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class _ChartSpec:
    title: str
    y_label: str
    value_format: ValueFormat
    queries: tuple[_SeriesQuery, ...] = ()
    derived: str | None = None


@dataclass(frozen=True, slots=True)
class ChartData:
    """Presentation-ready series for one dashboard chart."""

    title: str
    y_label: str
    value_format: ValueFormat
    series: tuple[Series, ...]


@dataclass(frozen=True, slots=True)
class DashboardData:
    """One immutable local-store dashboard refresh."""

    subsystem: str
    range_key: str
    recording_started_at: int | None
    has_samples: bool
    active_agents: float
    active_workspaces: float
    active_beads: float
    runs_in_range: float
    error_rate: float
    agent_sparkline: tuple[float, ...]
    workspace_sparkline: tuple[float, ...]
    bead_sparkline: tuple[float, ...]
    runs_sparkline: tuple[float, ...]
    error_sparkline: tuple[float, ...]
    charts: tuple[ChartData, ...]


_AGENT_TOKEN_QUERIES = (
    _SeriesQuery(
        "sase_llm_input_tokens_total",
        "counter",
        "sum",
        ("provider",),
        label="input",
    ),
    _SeriesQuery(
        "sase_llm_output_tokens_total",
        "counter",
        "sum",
        ("provider",),
        label="output",
    ),
)

_CHART_SETS: dict[str, tuple[_ChartSpec, ...]] = {
    "agents": (
        _ChartSpec(
            "Agent Runs by status",
            "runs",
            "number",
            (_SeriesQuery("sase_agent_runs_total", "counter", "sum", ("status",)),),
        ),
        _ChartSpec(
            "Run Duration p50/p95",
            "duration",
            "duration",
            (
                _SeriesQuery(
                    "sase_agent_run_duration_seconds",
                    "histogram",
                    "quantile",
                    quantile=0.50,
                    label="p50",
                ),
                _SeriesQuery(
                    "sase_agent_run_duration_seconds",
                    "histogram",
                    "quantile",
                    quantile=0.95,
                    label="p95",
                ),
            ),
        ),
        _ChartSpec("LLM Tokens by provider", "tokens", "tokens", _AGENT_TOKEN_QUERIES),
        _ChartSpec("Error Rate %", "error rate", "percent", derived="agent_error_rate"),
    ),
    "axe": (
        _ChartSpec(
            "Axe Cycles",
            "cycles",
            "number",
            (_SeriesQuery("sase_axe_cycles_total", "counter", "sum", ("cycle_type",)),),
        ),
        _ChartSpec(
            "Cycle Duration p50/p95",
            "duration",
            "duration",
            (
                _SeriesQuery(
                    "sase_axe_cycle_duration_seconds",
                    "histogram",
                    "quantile",
                    quantile=0.50,
                    label="p50",
                ),
                _SeriesQuery(
                    "sase_axe_cycle_duration_seconds",
                    "histogram",
                    "quantile",
                    quantile=0.95,
                    label="p95",
                ),
            ),
        ),
        _ChartSpec(
            "Active Lumberjacks",
            "workers",
            "number",
            (_SeriesQuery("sase_axe_lumberjacks_active", "gauge", "avg"),),
        ),
        _ChartSpec(
            "Axe Errors",
            "errors",
            "number",
            (_SeriesQuery("sase_axe_errors_total", "counter", "sum", ("error_type",)),),
        ),
    ),
    "beads": (
        _ChartSpec(
            "Bead Operations",
            "operations",
            "number",
            (
                _SeriesQuery(
                    "sase_bead_operations_total", "counter", "sum", ("operation",)
                ),
            ),
        ),
        _ChartSpec(
            "Status Transitions",
            "transitions",
            "number",
            (
                _SeriesQuery(
                    "sase_bead_status_transitions_total",
                    "counter",
                    "sum",
                    ("to_status",),
                ),
            ),
        ),
        _ChartSpec(
            "Active Beads",
            "beads",
            "number",
            (_SeriesQuery("sase_bead_active", "gauge", "avg", ("status",)),),
        ),
    ),
    "hooks": (
        _ChartSpec(
            "Hook Executions",
            "executions",
            "number",
            (
                _SeriesQuery(
                    "sase_hook_executions_total",
                    "counter",
                    "sum",
                    ("hook_type", "status"),
                ),
            ),
        ),
        _ChartSpec(
            "Hook Duration p95",
            "duration",
            "duration",
            (
                _SeriesQuery(
                    "sase_hook_duration_seconds",
                    "histogram",
                    "quantile",
                    ("hook_type",),
                    quantile=0.95,
                    label="p95",
                ),
            ),
        ),
        _ChartSpec(
            "Workflow Executions",
            "executions",
            "number",
            (
                _SeriesQuery(
                    "sase_workflow_executions_total",
                    "counter",
                    "sum",
                    ("workflow", "status"),
                ),
            ),
        ),
        _ChartSpec(
            "Workflow Duration p95",
            "duration",
            "duration",
            (
                _SeriesQuery(
                    "sase_workflow_duration_seconds",
                    "histogram",
                    "quantile",
                    ("workflow",),
                    quantile=0.95,
                    label="p95",
                ),
            ),
        ),
    ),
    "llm": (
        _ChartSpec(
            "LLM Invocations",
            "invocations",
            "number",
            (
                _SeriesQuery(
                    "sase_llm_invocations_total",
                    "counter",
                    "sum",
                    ("provider", "status"),
                ),
            ),
        ),
        _ChartSpec(
            "LLM Duration p50/p95",
            "duration",
            "duration",
            (
                _SeriesQuery(
                    "sase_llm_invocation_duration_seconds",
                    "histogram",
                    "quantile",
                    quantile=0.50,
                    label="p50",
                ),
                _SeriesQuery(
                    "sase_llm_invocation_duration_seconds",
                    "histogram",
                    "quantile",
                    quantile=0.95,
                    label="p95",
                ),
            ),
        ),
        _ChartSpec("LLM Tokens by provider", "tokens", "tokens", _AGENT_TOKEN_QUERIES),
        _ChartSpec(
            "LLM Errors",
            "errors",
            "number",
            (_SeriesQuery("sase_llm_errors_total", "counter", "sum", ("provider",)),),
        ),
    ),
    "memory": (
        _ChartSpec(
            "Memory Proposals",
            "proposals",
            "number",
            (
                _SeriesQuery(
                    "sase_memory_proposals_proposed_total",
                    "counter",
                    "sum",
                    label="proposed",
                ),
                _SeriesQuery(
                    "sase_memory_proposals_approved_total",
                    "counter",
                    "sum",
                    label="approved",
                ),
                _SeriesQuery(
                    "sase_memory_proposals_rejected_total",
                    "counter",
                    "sum",
                    label="rejected",
                ),
            ),
        ),
    ),
    "notifications": (
        _ChartSpec(
            "Notifications Sent",
            "notifications",
            "number",
            (
                _SeriesQuery(
                    "sase_notifications_sent_total",
                    "counter",
                    "sum",
                    ("type", "status"),
                ),
            ),
        ),
    ),
    "workspace": (
        _ChartSpec(
            "Active Workspaces",
            "workspaces",
            "number",
            (_SeriesQuery("sase_workspace_active", "gauge", "avg", ("project",)),),
        ),
        _ChartSpec(
            "Workspace Acquisitions",
            "acquisitions",
            "number",
            (
                _SeriesQuery(
                    "sase_workspace_acquisitions_total",
                    "counter",
                    "sum",
                    ("project",),
                ),
            ),
        ),
        _ChartSpec(
            "Workspace Releases",
            "releases",
            "number",
            (
                _SeriesQuery(
                    "sase_workspace_releases_total",
                    "counter",
                    "sum",
                    ("project",),
                ),
            ),
        ),
        _ChartSpec(
            "VCS Operations",
            "operations",
            "number",
            (
                _SeriesQuery(
                    "sase_vcs_operations_total",
                    "counter",
                    "sum",
                    ("provider", "status"),
                ),
            ),
        ),
    ),
}


class _RangeCache:
    def __init__(self, *, start_ts: int, end_ts: int, step_seconds: int) -> None:
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.step_seconds = step_seconds
        self._results: dict[tuple[Any, ...], dict[str, Any]] = {}

    def get(self, query: _SeriesQuery) -> dict[str, Any]:
        key = (
            query.metric,
            query.kind,
            query.aggregation,
            query.group_by,
            query.filters,
            query.quantile,
        )
        if key not in self._results:
            self._results[key] = query_range(
                query.metric,
                kind=query.kind,
                start_ts=self.start_ts,
                end_ts=self.end_ts,
                step_seconds=self.step_seconds,
                filters=dict(query.filters),
                group_by=query.group_by,
                aggregation=query.aggregation,
                quantile=query.quantile,
            )
        return self._results[key]


def _label_for(query: _SeriesQuery, labels: dict[str, str]) -> str:
    label_values = " · ".join(value for _, value in sorted(labels.items()))
    if query.label and label_values:
        return f"{query.label} · {label_values}"
    if query.label:
        return query.label
    return label_values or str(query.aggregation)


def _series_for(query: _SeriesQuery, result: dict[str, Any]) -> list[Series]:
    rendered: list[Series] = []
    for index, item in enumerate(result.get("series", [])):
        labels = dict(item.get("labels", {}))
        rendered.append(
            Series.from_pairs(
                f"{query.metric}:{query.aggregation}:{query.quantile}:{index}:{sorted(labels.items())}",
                [
                    (int(point["ts"]), float(point["value"]))
                    for point in item.get("points", [])
                ],
                label=_label_for(query, labels),
            )
        )
    return rendered


def _points_by_timestamp(result: dict[str, Any]) -> dict[int, float]:
    points: dict[int, float] = {}
    for item in result.get("series", []):
        for point in item.get("points", []):
            ts = int(point["ts"])
            points[ts] = points.get(ts, 0.0) + float(point["value"])
    return points


def _error_rate_series(cache: _RangeCache) -> Series:
    total = _points_by_timestamp(
        cache.get(_SeriesQuery("sase_agent_runs_total", "counter", "sum"))
    )
    errors = _points_by_timestamp(
        cache.get(
            _SeriesQuery(
                "sase_agent_runs_total",
                "counter",
                "sum",
                filters=(("status", "error"),),
            )
        )
    )
    points = [
        (ts, errors.get(ts, 0.0) / value * 100.0 if value else 0.0)
        for ts, value in sorted(total.items())
    ]
    return Series.from_pairs("agent-error-rate", points, label="errors")


def _chart_data(spec: _ChartSpec, cache: _RangeCache) -> ChartData:
    if spec.derived == "agent_error_rate":
        series = [_error_rate_series(cache)]
    else:
        series = [
            item
            for query in spec.queries
            for item in _series_for(query, cache.get(query))
        ]
    return ChartData(
        title=spec.title,
        y_label=spec.y_label,
        value_format=spec.value_format,
        series=tuple(series),
    )


def _instant_total(metric: str, kind: str, *, now_ts: int) -> float:
    result = query_instant(metric, kind=kind, group_by=(), now_ts=now_ts)
    return sum(float(value.get("value", 0.0)) for value in result.get("values", []))


def _range_values(cache: _RangeCache, query: _SeriesQuery) -> tuple[float, ...]:
    return tuple(
        value for _, value in sorted(_points_by_timestamp(cache.get(query)).items())
    )


def load_dashboard_data(
    *, now_ts: int, range_key: str, subsystem: str
) -> DashboardData:
    """Load one complete dashboard refresh from the configured local store."""
    stats = store_stats()
    sample_count = sum(
        int(stats.get(key, 0))
        for key in ("raw_sample_count", "rollup_5m_count", "rollup_1h_count")
    )
    has_samples = sample_count > 0
    empty = DashboardData(
        subsystem=subsystem,
        range_key=range_key,
        recording_started_at=stats.get("earliest_sample_ts"),
        has_samples=False,
        active_agents=0.0,
        active_workspaces=0.0,
        active_beads=0.0,
        runs_in_range=0.0,
        error_rate=0.0,
        agent_sparkline=(),
        workspace_sparkline=(),
        bead_sparkline=(),
        runs_sparkline=(),
        error_sparkline=(),
        charts=(),
    )
    if not has_samples:
        return empty

    start_ts = now_ts - RANGE_SECONDS[range_key]
    cache = _RangeCache(
        start_ts=start_ts,
        end_ts=now_ts,
        step_seconds=STEP_SECONDS[range_key],
    )
    agent_query = _SeriesQuery("sase_agent_active", "gauge", "avg")
    workspace_query = _SeriesQuery("sase_workspace_active", "gauge", "avg")
    bead_query = _SeriesQuery("sase_bead_active", "gauge", "avg")
    runs_query = _SeriesQuery("sase_agent_runs_total", "counter", "sum")
    runs_values = _range_values(cache, runs_query)
    error_values = tuple(point.value for point in _error_rate_series(cache).points)
    runs_in_range = sum(runs_values)
    errors_in_range = sum(
        _range_values(
            cache,
            _SeriesQuery(
                "sase_agent_runs_total",
                "counter",
                "sum",
                filters=(("status", "error"),),
            ),
        )
    )
    error_rate = errors_in_range / runs_in_range * 100.0 if runs_in_range else 0.0

    chart_specs = _CHART_SETS.get(subsystem, _CHART_SETS["agents"])
    return DashboardData(
        subsystem=subsystem,
        range_key=range_key,
        recording_started_at=stats.get("earliest_sample_ts"),
        has_samples=True,
        active_agents=_instant_total("sase_agent_active", "gauge", now_ts=now_ts),
        active_workspaces=_instant_total(
            "sase_workspace_active", "gauge", now_ts=now_ts
        ),
        active_beads=_instant_total("sase_bead_active", "gauge", now_ts=now_ts),
        runs_in_range=runs_in_range,
        error_rate=error_rate,
        agent_sparkline=_range_values(cache, agent_query),
        workspace_sparkline=_range_values(cache, workspace_query),
        bead_sparkline=_range_values(cache, bead_query),
        runs_sparkline=runs_values,
        error_sparkline=error_values,
        charts=tuple(_chart_data(spec, cache) for spec in chart_specs),
    )


def _error_status(rate: float) -> Status:
    thresholds = get_telemetry_config().health_thresholds
    if rate >= thresholds.error_rate_critical:
        return "critical"
    if rate >= thresholds.error_rate_warn:
        return "warning"
    return "ok"


def _render_dashboard(data: DashboardData, *, width: int) -> Group:
    """Render an immutable dashboard refresh with the shared chart toolkit."""
    header = Text.assemble(
        ("Telemetry Dashboard", "bold"),
        ("  ·  ", "dim"),
        (data.subsystem.title(), "cyan bold"),
        ("  ·  ", "dim"),
        (data.range_key, "cyan"),
    )
    if not data.has_samples:
        empty = Panel(
            "[dim]No telemetry samples have been recorded yet.\n"
            "Run normal SASE activity and refresh this dashboard.[/dim]",
            title="Local telemetry store",
            border_style="cyan",
        )
        return Group(header, Text(""), empty)

    tile_width = max(18, min(26, (max(width, 80) - 4) // 5))
    tiles = [
        render_stat_tile(
            data.active_agents,
            caption="Active Agents",
            width=tile_width,
            sparkline=data.agent_sparkline,
        ),
        render_stat_tile(
            data.active_workspaces,
            caption="Active Workspaces",
            width=tile_width,
            sparkline=data.workspace_sparkline,
        ),
        render_stat_tile(
            data.active_beads,
            caption="Active Beads",
            width=tile_width,
            sparkline=data.bead_sparkline,
        ),
        render_stat_tile(
            data.runs_in_range,
            caption=f"Runs · {data.range_key}",
            width=tile_width,
            sparkline=data.runs_sparkline,
        ),
        render_stat_tile(
            data.error_rate,
            caption="Error Rate",
            width=tile_width,
            value_format="percent",
            sparkline=data.error_sparkline,
            status=_error_status(data.error_rate),
            lower_is_better=True,
        ),
    ]
    chart_width = max(32, (max(width, 70) - 3) // 2)
    charts = [
        render_line_chart(
            chart.series,
            title=chart.title,
            width=chart_width,
            height=15,
            y_label=chart.y_label,
            value_format=chart.value_format,
            recording_started_at=data.recording_started_at,
        )
        for chart in data.charts
    ]
    return Group(
        header,
        Text(""),
        Columns(tiles, equal=True, expand=False),
        Text(""),
        Columns(charts, equal=True, expand=False, column_first=True),
    )


def handle_telemetry_dashboard(args: argparse.Namespace) -> None:
    """Run the live, auto-refreshing local telemetry dashboard."""
    config = get_telemetry_config()
    console = Console()
    if not config.enabled:
        console.print(
            "[yellow]Telemetry is disabled.[/yellow]\n"
            "[dim]Set telemetry.enabled to true to begin recording.[/dim]"
        )
        return

    interval = max(1, int(getattr(args, "interval", 5)))
    range_key = str(getattr(args, "range", "1h"))
    subsystem = str(getattr(args, "subsystem", "agents"))
    try:
        with Live(console=console, refresh_per_second=4) as live:
            while True:
                try:
                    data = load_dashboard_data(
                        now_ts=int(time.time()),
                        range_key=range_key,
                        subsystem=subsystem,
                    )
                    live.update(_render_dashboard(data, width=console.width))
                except (RuntimeError, ValueError) as exc:
                    live.update(
                        Panel(
                            f"[red]Unable to query the local telemetry store:[/red]\n{exc}",
                            title="Telemetry Dashboard",
                            border_style="red",
                        )
                    )
                time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard stopped.[/dim]")


__all__ = [
    "ChartData",
    "DashboardData",
    "handle_telemetry_dashboard",
    "load_dashboard_data",
]
