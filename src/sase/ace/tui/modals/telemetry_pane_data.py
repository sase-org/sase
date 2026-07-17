"""Off-thread query and model building for the Admin Center Telemetry pane."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from sase.telemetry._config import HealthThresholds
from sase.telemetry.render import (
    Point,
    Series,
    Status,
    ValueFormat,
    categorical_color,
    status_color,
)

TelemetryRange = Literal["15m", "1h", "6h", "24h", "7d"]
TelemetrySubsystem = Literal[
    "agents",
    "llm",
    "axe",
    "hooks",
    "beads",
    "vcs",
    "notifications",
    "memory",
]

RANGE_ORDER: tuple[TelemetryRange, ...] = ("15m", "1h", "6h", "24h", "7d")
RANGE_SECONDS: dict[TelemetryRange, int] = {
    "15m": 15 * 60,
    "1h": 60 * 60,
    "6h": 6 * 60 * 60,
    "24h": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
}
RANGE_STEPS: dict[TelemetryRange, int] = {
    "15m": 15,
    "1h": 60,
    "6h": 5 * 60,
    "24h": 15 * 60,
    "7d": 60 * 60,
}

SUBSYSTEM_ORDER: tuple[TelemetrySubsystem, ...] = (
    "agents",
    "llm",
    "axe",
    "hooks",
    "beads",
    "vcs",
    "notifications",
    "memory",
)
SUBSYSTEM_LABELS: dict[TelemetrySubsystem, str] = {
    "agents": "Agents",
    "llm": "LLM",
    "axe": "Axe",
    "hooks": "Hooks",
    "beads": "Beads",
    "vcs": "VCS / Workspaces",
    "notifications": "Notifications",
    "memory": "Memory",
}


@dataclass(frozen=True, slots=True)
class _TelemetryTileData:
    """Immutable input for one stat tile."""

    caption: str
    value: float | str | None
    key: str
    value_format: ValueFormat = "number"
    delta: float | None = None
    lower_is_better: bool = False
    sparkline: tuple[float, ...] | None = None
    status: Status | None = None


@dataclass(frozen=True, slots=True)
class _TelemetryChartData:
    """Immutable input for one line chart."""

    title: str
    series: tuple[Series, ...]
    value_format: ValueFormat = "number"
    y_label: str = ""
    y_min: float | None = None
    y_max: float | None = None


@dataclass(frozen=True, slots=True)
class TelemetryViewData:
    """Complete frozen result painted by :class:`TelemetryPane`."""

    subsystem: TelemetrySubsystem
    range_key: TelemetryRange
    generated_at: int
    recording_started_at: int | None
    enabled: bool
    empty: bool
    store_path: str
    tiles: tuple[_TelemetryTileData, ...]
    charts: tuple[_TelemetryChartData, ...]
    health_status: Status | None
    health_text: str


class _TelemetryConfigLike(Protocol):
    @property
    def enabled(self) -> bool: ...

    @property
    def busy_timeout_ms(self) -> int: ...

    @property
    def health_thresholds(self) -> HealthThresholds: ...

    @property
    def resolved_store_path(self) -> Path: ...


def _empty_telemetry_view(
    subsystem: TelemetrySubsystem,
    range_key: TelemetryRange,
    *,
    generated_at: int,
    enabled: bool = True,
    store_path: str = "",
) -> TelemetryViewData:
    """Return a fully-shaped empty result for disabled and empty stores."""

    tiles = tuple(
        _TelemetryTileData(
            caption=caption,
            value=None,
            key=key,
            value_format=cast(ValueFormat, fmt),
        )
        for caption, key, fmt in (
            ("Active Agents", "agents", "number"),
            ("Active Workspaces", "workspaces", "number"),
            ("Active Beads", "beads", "number"),
            ("Runs in range", "runs", "number"),
            ("Error rate", "errors", "percent"),
        )
    )
    charts = tuple(
        _TelemetryChartData(title=title, series=())
        for title in _empty_chart_titles(subsystem)
    )
    health_text = (
        "Telemetry is disabled in config"
        if not enabled
        else "Health · no telemetry samples recorded yet"
    )
    return TelemetryViewData(
        subsystem=subsystem,
        range_key=range_key,
        generated_at=generated_at,
        recording_started_at=None,
        enabled=enabled,
        empty=True,
        store_path=store_path,
        tiles=cast(tuple[_TelemetryTileData, ...], tiles),
        charts=cast(tuple[_TelemetryChartData, ...], charts),
        health_status=None,
        health_text=health_text,
    )


class _TelemetryReader:
    """One-refresh query facade with duplicate-request caching."""

    def __init__(
        self,
        config: _TelemetryConfigLike,
        *,
        start_ts: int,
        end_ts: int,
        step_seconds: int,
    ) -> None:
        self.config = config
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.step_seconds = step_seconds
        self._range_cache: dict[tuple[object, ...], dict[str, Any]] = {}
        self._instant_cache: dict[tuple[object, ...], dict[str, Any]] = {}

    def range_series(
        self,
        metric: str,
        *,
        group_by: tuple[str, ...] = (),
        aggregation: str = "sum",
        start_ts: int | None = None,
        end_ts: int | None = None,
        key_prefix: str = "",
    ) -> tuple[Series, ...]:
        """Query and normalize grouped range series."""

        query_start = self.start_ts if start_ts is None else start_ts
        query_end = self.end_ts if end_ts is None else end_ts
        cache_key = (
            metric,
            query_start,
            query_end,
            self.step_seconds,
            aggregation,
            group_by,
        )
        response = self._range_cache.get(cache_key)
        if response is None:
            from sase_core_rs import telemetry_query_range  # type: ignore[import-untyped]

            request = {
                "metric": metric,
                "start_ts": query_start,
                "end_ts": query_end,
                "step_seconds": self.step_seconds,
                "aggregation": aggregation,
                "group_by": list(group_by),
            }
            response = telemetry_query_range(
                str(self.config.resolved_store_path),
                request,
                self.config.busy_timeout_ms,
            )
            self._range_cache[cache_key] = response
        return _series_from_response(response, key_prefix=key_prefix or metric)

    def instant_total(self, metric: str) -> float | None:
        """Return the current value aggregated across all labels."""

        cache_key = (metric, self.end_ts)
        response = self._instant_cache.get(cache_key)
        if response is None:
            from sase_core_rs import telemetry_query_instant  # type: ignore[import-untyped]

            response = telemetry_query_instant(
                str(self.config.resolved_store_path),
                {"metric": metric, "group_by": [], "now_ts": self.end_ts},
                self.config.busy_timeout_ms,
            )
            self._instant_cache[cache_key] = response
        values = response.get("values", [])
        found = False
        total = 0.0
        for item in values if isinstance(values, list) else []:
            if not isinstance(item, dict) or "value" not in item:
                continue
            total += float(item["value"])
            found = True
        return total if found else None


def load_telemetry_view(
    subsystem: TelemetrySubsystem,
    range_key: TelemetryRange,
    *,
    now_ts: int | None = None,
) -> TelemetryViewData:
    """Load store data and build chart models entirely off the UI thread."""

    from sase.telemetry._config import get_telemetry_config

    generated_at = int(time.time()) if now_ts is None else int(now_ts)
    config = get_telemetry_config()
    store_path = str(config.resolved_store_path)
    if not config.enabled:
        return _empty_telemetry_view(
            subsystem,
            range_key,
            generated_at=generated_at,
            enabled=False,
            store_path=store_path,
        )

    from sase_core_rs import telemetry_store_stats  # type: ignore[import-untyped]

    stats = telemetry_store_stats(store_path, config.busy_timeout_ms)
    sample_count = sum(
        int(stats.get(key, 0) or 0)
        for key in ("raw_sample_count", "rollup_5m_count", "rollup_1h_count")
    )
    if sample_count == 0:
        return _empty_telemetry_view(
            subsystem,
            range_key,
            generated_at=generated_at,
            store_path=store_path,
        )

    duration = RANGE_SECONDS[range_key]
    reader = _TelemetryReader(
        config,
        start_ts=generated_at - duration,
        end_ts=generated_at,
        step_seconds=RANGE_STEPS[range_key],
    )
    agent_runs = reader.range_series(
        "sase_agent_runs_total",
        group_by=("status",),
        key_prefix="agent-runs",
    )
    previous_agent_runs = reader.range_series(
        "sase_agent_runs_total",
        group_by=("status",),
        start_ts=generated_at - 2 * duration,
        end_ts=generated_at - duration,
        key_prefix="previous-agent-runs",
    )
    error_rate = _error_rate_series(agent_runs)
    previous_error_rate = _error_rate_series(previous_agent_runs)
    tiles = _build_tiles(
        reader,
        agent_runs=agent_runs,
        previous_agent_runs=previous_agent_runs,
        error_rate=error_rate,
        previous_error_rate=previous_error_rate,
    )
    charts = _build_charts(
        reader,
        subsystem,
        agent_runs=agent_runs,
        error_rate=error_rate,
    )
    health_status, health_text = _build_health(
        reader,
        agent_runs=agent_runs,
        thresholds=config.health_thresholds,
    )
    earliest = stats.get("earliest_sample_ts")
    return TelemetryViewData(
        subsystem=subsystem,
        range_key=range_key,
        generated_at=generated_at,
        recording_started_at=int(earliest) if earliest is not None else None,
        enabled=True,
        empty=False,
        store_path=store_path,
        tiles=tiles,
        charts=charts,
        health_status=health_status,
        health_text=health_text,
    )


def _series_from_response(
    response: dict[str, Any],
    *,
    key_prefix: str,
) -> tuple[Series, ...]:
    result: list[Series] = []
    raw_series = response.get("series", [])
    for index, item in enumerate(raw_series if isinstance(raw_series, list) else []):
        if not isinstance(item, dict):
            continue
        labels_raw = item.get("labels", {})
        labels = labels_raw if isinstance(labels_raw, dict) else {}
        label_parts = [str(labels[key]) for key in sorted(labels)]
        label = " · ".join(label_parts) if label_parts else "Total"
        identity = "|".join(label_parts) if label_parts else "total"
        points: list[Point] = []
        for point in item.get("points", []):
            if not isinstance(point, dict):
                continue
            try:
                points.append(Point(int(point["ts"]), float(point["value"])))
            except (KeyError, TypeError, ValueError):
                continue
        semantic_status = _semantic_status(labels)
        color = (
            status_color(semantic_status)
            if semantic_status is not None
            else categorical_color(identity)
        )
        result.append(
            Series(
                key=f"{key_prefix}:{identity}:{index}",
                label=label,
                color=color,
                points=tuple(points),
            )
        )
    return tuple(result)


def _semantic_status(labels: dict[str, Any]) -> Status | None:
    raw = str(labels.get("status", labels.get("to_status", ""))).lower()
    if raw in {"ok", "success", "healthy", "closed", "submitted"}:
        return "ok"
    if raw in {"warning", "warn", "retry", "in_progress", "draft", "ready"}:
        return "warning"
    if raw in {"critical", "error", "failed", "failure", "rejected"}:
        return "critical"
    return None


def _renamed(
    series: tuple[Series, ...],
    *,
    label: str,
    key_prefix: str,
) -> tuple[Series, ...]:
    return tuple(
        Series(
            key=f"{key_prefix}:{item.key}",
            label=(
                label
                if item.resolved_label == "Total"
                else f"{label} · {item.resolved_label}"
            ),
            color=categorical_color(f"{key_prefix}:{item.resolved_label}"),
            points=item.points,
        )
        for item in series
    )


def _quantile_series(
    reader: _TelemetryReader,
    metric: str,
) -> tuple[Series, ...]:
    p50 = reader.range_series(metric, aggregation="p50", key_prefix=f"{metric}:p50")
    p95 = reader.range_series(metric, aggregation="p95", key_prefix=f"{metric}:p95")
    return _renamed(p50, label="p50", key_prefix="p50") + _renamed(
        p95, label="p95", key_prefix="p95"
    )


def _combined_metric_series(
    reader: _TelemetryReader,
    specs: tuple[tuple[str, str], ...],
    *,
    group_by: tuple[str, ...] = (),
    aggregation: str = "sum",
) -> tuple[Series, ...]:
    combined: tuple[Series, ...] = ()
    for metric, label in specs:
        queried = reader.range_series(
            metric,
            group_by=group_by,
            aggregation=aggregation,
            key_prefix=label.lower().replace(" ", "-"),
        )
        combined += _renamed(
            queried,
            label=label,
            key_prefix=label.lower().replace(" ", "-"),
        )
    return combined


def _series_total(series: tuple[Series, ...]) -> float:
    return sum(point.value for item in series for point in item.points)


def _timestamp_int(timestamp: float | int | datetime) -> int:
    if isinstance(timestamp, datetime):
        return int(timestamp.timestamp())
    return int(timestamp)


def _bucket_totals(series: tuple[Series, ...]) -> tuple[float, ...]:
    totals: dict[int, float] = {}
    for item in series:
        for point in item.points:
            timestamp = _timestamp_int(point.timestamp)
            totals[timestamp] = totals.get(timestamp, 0.0) + point.value
    return tuple(totals[key] for key in sorted(totals))


def _error_rate_series(series: tuple[Series, ...]) -> tuple[Series, ...]:
    totals: dict[int, float] = {}
    errors: dict[int, float] = {}
    for item in series:
        is_error = any(
            token in item.resolved_label.lower()
            for token in ("error", "failed", "failure", "critical")
        )
        for point in item.points:
            timestamp = _timestamp_int(point.timestamp)
            totals[timestamp] = totals.get(timestamp, 0.0) + point.value
            if is_error:
                errors[timestamp] = errors.get(timestamp, 0.0) + point.value
    points = tuple(
        Point(timestamp, errors.get(timestamp, 0.0) / total * 100.0)
        for timestamp, total in sorted(totals.items())
        if total > 0
    )
    if not points:
        return ()
    return (
        Series(
            key="agent-error-rate",
            label="Error rate",
            color=status_color("critical"),
            points=points,
        ),
    )


def _latest_or_none(series: tuple[Series, ...]) -> float | None:
    points = [point for item in series for point in item.points]
    if not points:
        return None
    return max(points, key=lambda point: _timestamp_int(point.timestamp)).value


def _percent_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        return None if current == 0 else 100.0
    return (current - previous) / previous * 100.0


def _rate_status(rate: float | None, thresholds: HealthThresholds) -> Status | None:
    if rate is None:
        return None
    if rate >= thresholds.error_rate_critical:
        return "critical"
    if rate >= thresholds.error_rate_warn:
        return "warning"
    return "ok"


def _build_tiles(
    reader: _TelemetryReader,
    *,
    agent_runs: tuple[Series, ...],
    previous_agent_runs: tuple[Series, ...],
    error_rate: tuple[Series, ...],
    previous_error_rate: tuple[Series, ...],
) -> tuple[_TelemetryTileData, ...]:
    runs = _series_total(agent_runs)
    previous_runs = _series_total(previous_agent_runs)
    error = _latest_or_none(error_rate)
    previous_error = _latest_or_none(previous_error_rate)
    return (
        _TelemetryTileData(
            "Active Agents",
            reader.instant_total("sase_agent_active") or 0.0,
            "agents",
        ),
        _TelemetryTileData(
            "Active Workspaces",
            reader.instant_total("sase_workspace_active") or 0.0,
            "workspaces",
        ),
        _TelemetryTileData(
            "Active Beads",
            reader.instant_total("sase_bead_active") or 0.0,
            "beads",
        ),
        _TelemetryTileData(
            "Runs in range",
            runs,
            "runs",
            delta=_percent_delta(runs, previous_runs),
            sparkline=_bucket_totals(agent_runs) or None,
        ),
        _TelemetryTileData(
            "Error rate",
            error or 0.0,
            "errors",
            value_format="percent",
            delta=_percent_delta(error, previous_error),
            lower_is_better=True,
            sparkline=tuple(point.value for item in error_rate for point in item.points)
            or None,
            status=_rate_status(error, reader.config.health_thresholds),
        ),
    )


def _build_charts(
    reader: _TelemetryReader,
    subsystem: TelemetrySubsystem,
    *,
    agent_runs: tuple[Series, ...],
    error_rate: tuple[Series, ...],
) -> tuple[_TelemetryChartData, ...]:
    if subsystem == "agents":
        tokens = _combined_metric_series(
            reader,
            (
                ("sase_llm_input_tokens_total", "Input"),
                ("sase_llm_output_tokens_total", "Output"),
            ),
            group_by=("provider",),
        )
        return (
            _TelemetryChartData("Agent Runs by status", agent_runs),
            _TelemetryChartData(
                "Run Duration p50 / p95",
                _quantile_series(reader, "sase_agent_run_duration_seconds"),
                value_format="duration",
                y_label="duration",
            ),
            _TelemetryChartData(
                "LLM Tokens by provider",
                tokens,
                value_format="tokens",
                y_label="tokens",
            ),
            _TelemetryChartData(
                "Error Rate %",
                error_rate,
                value_format="percent",
                y_label="errors",
                y_min=0.0,
                y_max=100.0,
            ),
        )
    if subsystem == "llm":
        tokens = _combined_metric_series(
            reader,
            (
                ("sase_llm_input_tokens_total", "Input"),
                ("sase_llm_output_tokens_total", "Output"),
                ("sase_llm_cache_read_tokens_total", "Cache"),
            ),
            group_by=("provider",),
        )
        return (
            _counter_chart(
                reader,
                "LLM Invocations by status",
                "sase_llm_invocations_total",
                ("status",),
            ),
            _TelemetryChartData(
                "Invocation Duration p50 / p95",
                _quantile_series(reader, "sase_llm_invocation_duration_seconds"),
                value_format="duration",
            ),
            _TelemetryChartData("Tokens by provider", tokens, value_format="tokens"),
            _counter_chart(
                reader,
                "Errors by provider",
                "sase_llm_errors_total",
                ("provider",),
            ),
        )
    if subsystem == "axe":
        return (
            _counter_chart(
                reader, "Cycles by type", "sase_axe_cycles_total", ("cycle_type",)
            ),
            _TelemetryChartData(
                "Cycle Duration p50 / p95",
                _quantile_series(reader, "sase_axe_cycle_duration_seconds"),
                value_format="duration",
            ),
            _counter_chart(
                reader,
                "Active Lumberjacks",
                "sase_axe_lumberjacks_active",
                (),
                aggregation="avg",
            ),
            _counter_chart(
                reader, "Errors by type", "sase_axe_errors_total", ("error_type",)
            ),
        )
    if subsystem == "hooks":
        return (
            _counter_chart(
                reader,
                "Hook Executions by status",
                "sase_hook_executions_total",
                ("status",),
            ),
            _TelemetryChartData(
                "Hook Duration p50 / p95",
                _quantile_series(reader, "sase_hook_duration_seconds"),
                value_format="duration",
            ),
            _counter_chart(
                reader,
                "Workflow Executions by status",
                "sase_workflow_executions_total",
                ("status",),
            ),
            _counter_chart(
                reader,
                "Hook Retries by type",
                "sase_hook_retries_total",
                ("hook_type",),
            ),
        )
    if subsystem == "beads":
        return (
            _counter_chart(
                reader,
                "Operations by type",
                "sase_bead_operations_total",
                ("operation",),
            ),
            _counter_chart(
                reader,
                "Transitions by destination",
                "sase_bead_status_transitions_total",
                ("to_status",),
            ),
            _counter_chart(
                reader,
                "Active Beads by status",
                "sase_bead_active",
                ("status",),
                aggregation="avg",
            ),
            _counter_chart(
                reader,
                "Operation Rate",
                "sase_bead_operations_total",
                (),
                aggregation="rate",
            ),
        )
    if subsystem == "vcs":
        workspace_flow = _combined_metric_series(
            reader,
            (
                ("sase_workspace_acquisitions_total", "Acquired"),
                ("sase_workspace_releases_total", "Released"),
            ),
        )
        return (
            _counter_chart(
                reader, "Commits by provider", "sase_vcs_commits_total", ("provider",)
            ),
            _counter_chart(
                reader,
                "VCS Operations by status",
                "sase_vcs_operations_total",
                ("status",),
            ),
            _TelemetryChartData("Workspace Flow", workspace_flow),
            _counter_chart(
                reader,
                "Active Workspaces by project",
                "sase_workspace_active",
                ("project",),
                aggregation="avg",
            ),
        )
    if subsystem == "notifications":
        return (
            _counter_chart(
                reader,
                "Notifications by type",
                "sase_notifications_sent_total",
                ("type",),
            ),
            _counter_chart(
                reader,
                "Delivery by status",
                "sase_notifications_sent_total",
                ("status",),
            ),
            _counter_chart(
                reader, "Notifications Sent", "sase_notifications_sent_total", ()
            ),
            _counter_chart(
                reader,
                "Notification Rate",
                "sase_notifications_sent_total",
                (),
                aggregation="rate",
            ),
        )

    outcomes = _combined_metric_series(
        reader,
        (
            ("sase_memory_proposals_proposed_total", "Proposed"),
            ("sase_memory_proposals_approved_total", "Approved"),
            ("sase_memory_proposals_rejected_total", "Rejected"),
        ),
    )
    return (
        _counter_chart(
            reader, "Proposals Created", "sase_memory_proposals_proposed_total", ()
        ),
        _counter_chart(
            reader,
            "Approvals by edit state",
            "sase_memory_proposals_approved_total",
            ("edited",),
        ),
        _counter_chart(
            reader, "Proposals Rejected", "sase_memory_proposals_rejected_total", ()
        ),
        _TelemetryChartData("Proposal Outcomes", outcomes),
    )


def _counter_chart(
    reader: _TelemetryReader,
    title: str,
    metric: str,
    group_by: tuple[str, ...],
    *,
    aggregation: str = "sum",
) -> _TelemetryChartData:
    return _TelemetryChartData(
        title,
        reader.range_series(
            metric,
            group_by=group_by,
            aggregation=aggregation,
            key_prefix=metric,
        ),
    )


def _health_rate(
    series: tuple[Series, ...],
    *,
    error_tokens: tuple[str, ...],
) -> tuple[float, float]:
    total = _series_total(series)
    errors = sum(
        point.value
        for item in series
        if any(token in item.resolved_label.lower() for token in error_tokens)
        for point in item.points
    )
    return total, errors / total * 100.0 if total else 0.0


def _build_health(
    reader: _TelemetryReader,
    *,
    agent_runs: tuple[Series, ...],
    thresholds: HealthThresholds,
) -> tuple[Status | None, str]:
    statuses: list[Status] = []
    details: list[str] = []

    agent_total, agent_rate = _health_rate(agent_runs, error_tokens=("error", "fail"))
    if agent_total:
        status = _rate_status(agent_rate, thresholds) or "ok"
        statuses.append(status)
        details.append(f"Agents {agent_rate:.1f}% errors")

    llm = reader.range_series(
        "sase_llm_invocations_total",
        group_by=("status",),
        key_prefix="health-llm",
    )
    llm_total, llm_rate = _health_rate(llm, error_tokens=("error", "fail"))
    if llm_total:
        status = _rate_status(llm_rate, thresholds) or "ok"
        statuses.append(status)
        details.append(f"LLM {llm_rate:.1f}% errors")

    axe_cycles = _series_total(
        reader.range_series("sase_axe_cycles_total", key_prefix="health-axe-cycles")
    )
    axe_errors = _series_total(
        reader.range_series("sase_axe_errors_total", key_prefix="health-axe-errors")
    )
    if axe_cycles or axe_errors:
        axe_status: Status = (
            "critical" if axe_errors >= 5 else "warning" if axe_errors else "ok"
        )
        statuses.append(axe_status)
        details.append(f"Axe {axe_errors:g} errors")

    hook_executions = _series_total(
        reader.range_series(
            "sase_hook_executions_total", key_prefix="health-hook-executions"
        )
    )
    hook_retries = _series_total(
        reader.range_series("sase_hook_retries_total", key_prefix="health-hook-retries")
    )
    if hook_executions:
        retry_rate = hook_retries / hook_executions * 100.0
        if retry_rate >= thresholds.retry_rate_critical:
            hook_status: Status = "critical"
        elif retry_rate >= thresholds.retry_rate_warn:
            hook_status = "warning"
        else:
            hook_status = "ok"
        statuses.append(hook_status)
        details.append(f"Hooks {retry_rate:.1f}% retries")

    if not statuses:
        return None, "Health · no activity in selected range"
    overall: Status = (
        "critical"
        if "critical" in statuses
        else "warning"
        if "warning" in statuses
        else "ok"
    )
    label = {"ok": "HEALTHY", "warning": "DEGRADED", "critical": "CRITICAL"}[overall]
    return overall, f"{label} · " + " · ".join(details)


def _empty_chart_titles(subsystem: TelemetrySubsystem) -> tuple[str, str, str, str]:
    titles: dict[TelemetrySubsystem, tuple[str, str, str, str]] = {
        "agents": (
            "Agent Runs by status",
            "Run Duration p50 / p95",
            "LLM Tokens by provider",
            "Error Rate %",
        ),
        "llm": (
            "LLM Invocations by status",
            "Invocation Duration p50 / p95",
            "Tokens by provider",
            "Errors by provider",
        ),
        "axe": (
            "Cycles by type",
            "Cycle Duration p50 / p95",
            "Active Lumberjacks",
            "Errors by type",
        ),
        "hooks": (
            "Hook Executions by status",
            "Hook Duration p50 / p95",
            "Workflow Executions by status",
            "Hook Retries by type",
        ),
        "beads": (
            "Operations by type",
            "Transitions by destination",
            "Active Beads by status",
            "Operation Rate",
        ),
        "vcs": (
            "Commits by provider",
            "VCS Operations by status",
            "Workspace Flow",
            "Active Workspaces by project",
        ),
        "notifications": (
            "Notifications by type",
            "Delivery by status",
            "Notifications Sent",
            "Notification Rate",
        ),
        "memory": (
            "Proposals Created",
            "Approvals by edit state",
            "Proposals Rejected",
            "Proposal Outcomes",
        ),
    }
    return titles[subsystem]


__all__ = [
    "RANGE_ORDER",
    "SUBSYSTEM_LABELS",
    "SUBSYSTEM_ORDER",
    "TelemetryRange",
    "TelemetrySubsystem",
    "TelemetryViewData",
    "load_telemetry_view",
]
