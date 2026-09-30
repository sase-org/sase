"""``sase tool stats`` readout over the ToolRun ledger.

Turns the ToolRun ledger into routine, read-only readouts: per tool, stage,
route, and provider p50/p90, outcome and censoring mix, ceiling kills and
wasted hours, repeats and duplicates, a daily trend, a chronological backtest,
and host pressure. The report itself is computed by the Rust core
(``sase_core::tool_run::tool_run_stats_report``); this module only validates
CLI arguments and presents the envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import platform
import sys
import time
from typing import Any

from rich.console import Console
from rich.table import Table

from sase.config.tools import tool_project_identity
from sase.core.tool_run import tool_run_stats_report
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.render import EMPTY, format_duration_ms, format_kib


class _StatsQueryError(ValueError):
    """User-facing stats usage error (exit 2)."""


@dataclass(frozen=True)
class ToolStatsCliRequest:
    include_all: bool
    days: int
    json: bool
    tool: str | None


def handle_stats(request: ToolStatsCliRequest) -> int:
    """Render ``sase tool stats``; 0 reported, 1 store failure, 2 usage."""

    try:
        days = _validate_days(request.days)
    except _StatsQueryError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    reconcile_unsettled_tool_runs()
    try:
        envelope = _build_envelope(
            include_all=request.include_all,
            days=days,
            tool=request.tool,
        )
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(f"stats report failed: {exc}", file=sys.stderr)
        return 1
    if request.json:
        print(json.dumps(envelope, indent=2, sort_keys=True))
        return 0
    _print_human(envelope, detail_tool=request.tool)
    for diagnostic in envelope.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0


def _validate_days(days: int) -> int:
    if type(days) is bool or not isinstance(days, int) or not 1 <= days <= 180:
        raise _StatsQueryError("-d/--days must be 1..180")
    return days


def _build_envelope(
    *, include_all: bool, days: int, tool: str | None
) -> dict[str, Any]:
    """Assemble the versioned stats envelope via the Rust core."""

    payload: dict[str, Any] = {
        "days": days,
        "now_ts": int(time.time()),
        "utc_offset_seconds": _local_utc_offset_seconds(),
    }
    if not include_all:
        payload["project"] = tool_project_identity()
    if tool:
        payload["tool_name"] = tool
    envelope = tool_run_stats_report(payload)
    envelope["host"] = platform.node()
    if envelope.get("schema_version") is None:
        envelope["schema_version"] = 1
    return envelope


def _local_utc_offset_seconds() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds()) if offset is not None else 0


def _print_human(envelope: dict[str, Any], *, detail_tool: str | None) -> None:
    tools = [t for t in envelope.get("tools") or () if isinstance(t, dict)]
    if not tools:
        print("no recorded runs")
        return
    window = envelope.get("window") or {}
    days = window.get("days", envelope.get("days", 7))
    since_ts = window.get("since_ts")
    project = envelope.get("project") or "all projects"
    host = envelope.get("host") or EMPTY
    runs_scanned = envelope.get(
        "runs_scanned", sum(int(t.get("runs") or 0) for t in tools)
    )
    adhoc = envelope.get("adhoc_runs", 0)
    console = Console(width=120, highlight=False)
    console.print(
        f"tool stats \u00b7 {project} \u00b7 {host} \u00b7 last {days}d"
        f" since {_format_since(since_ts)} \u00b7 {_fmt_int(runs_scanned)} runs"
        f" ({_fmt_int(adhoc)} ad-hoc)"
    )
    console.print()
    _print_tool_table(console, tools)
    console.print()
    if len(tools) != 1:
        console.print(
            "run `sase tool stats -t TOOL` for stages, routes, providers,"
            " trend, and signals"
        )
    _print_pressure_line(console, envelope.get("pressure") or {})
    if len(tools) == 1:
        _print_detail_sections(console, tools[0])
        _print_signal_lines(console, tools[0])
    for key in ("runs_truncated", "stages_truncated", "samples_truncated"):
        if envelope.get(key):
            console.print(
                f"{key.replace('_', ' ')}; narrowing days or tool keeps the whole window"
            )


def _print_tool_table(console: Console, tools: list[dict[str, Any]]) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("TOOL", no_wrap=True)
    table.add_column("RUNS", justify="right")
    table.add_column("OK", justify="right")
    table.add_column("FAIL", justify="right")
    table.add_column("CENS", justify="right")
    table.add_column("P50", no_wrap=True)
    table.add_column("P90", no_wrap=True)
    table.add_column("KILLED", justify="right")
    table.add_column("WASTE", justify="right")
    table.add_column("MON<2m", justify="right")
    for tool in tools:
        outcomes = tool.get("outcomes") or {}
        duration = tool.get("duration") or {}
        waste = tool.get("waste") or {}
        killed = waste.get("killed_at_ceiling") or {}
        monitor = tool.get("monitor_owned") or {}
        kills = int(killed.get("runs") or 0)
        table.add_row(
            str(tool.get("tool_name") or EMPTY),
            _fmt_int(tool.get("runs")),
            _fmt_int(outcomes.get("succeeded")),
            _fmt_int(outcomes.get("failed")),
            _fmt_int(outcomes.get("censored")),
            _fmt_ms(duration.get("p50_ms")),
            _fmt_ms(duration.get("p90_ms")),
            f"[red]{kills:,}[/red]" if kills else "0",
            _fmt_hours(waste.get("total_hours")),
            f"{_fmt_int(monitor.get('under_2m'))}/{_fmt_int(monitor.get('runs'))}",
        )
    console.print(table)


def _print_pressure_line(console: Console, pressure: dict[str, Any]) -> None:
    buckets = pressure.get("buckets", 0)
    busy = pressure.get("busy_buckets", 0)
    share = _fmt_share(pressure.get("memory_over_threshold_share"))
    busy_share = _fmt_share(pressure.get("busy_memory_over_threshold_share"))
    console.print(
        f"pressure \u00b7 {_fmt_int(buckets)} buckets ({_fmt_int(busy)} busy)"
        f" \u00b7 memory PSI >10: {share} (busy {busy_share})"
        f" \u00b7 p90 cpu {_fmt_num(pressure.get('cpu_psi_p90'))}"
        f" \u00b7 mem {_fmt_num(pressure.get('memory_psi_p90'))}"
        f" \u00b7 io {_fmt_num(pressure.get('io_psi_p90'))}"
        f" \u00b7 load/cpu {_fmt_num(pressure.get('load_per_cpu_p90'))}"
    )


def _print_detail_sections(console: Console, tool: dict[str, Any]) -> None:
    stages = [s for s in tool.get("stages") or () if isinstance(s, dict)]
    if stages:
        backtests = {
            b.get("description"): b.get("backtest") or {}
            for b in tool.get("stage_backtests") or ()
            if isinstance(b, dict)
        }
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("STAGE", no_wrap=True)
        table.add_column("RUNS", justify="right")
        table.add_column("OK", justify="right")
        table.add_column("FAIL", justify="right")
        table.add_column("INC", justify="right")
        table.add_column("P50", no_wrap=True)
        table.add_column("P90", no_wrap=True)
        table.add_column("P90/P50", justify="right")
        table.add_column("HOURS", justify="right")
        table.add_column("COV", justify="right")
        table.add_column("WIDTH", justify="right")
        for stage in stages:
            backtest = backtests.get(stage.get("description"), {})
            table.add_row(
                str(stage.get("description") or EMPTY),
                _fmt_int(stage.get("runs")),
                _fmt_int(stage.get("ok")),
                _fmt_int(stage.get("failed")),
                _fmt_int(stage.get("incomplete")),
                _fmt_ms(stage.get("p50_ms")),
                _fmt_ms(stage.get("p90_ms")),
                _fmt_ratio(stage.get("p90_over_p50")),
                _fmt_hours(stage.get("total_hours")),
                _fmt_coverage(backtest.get("coverage")),
                _fmt_width(backtest.get("median_width")),
            )
        console.print("STAGES")
        console.print(table)
    routes = [r for r in tool.get("routes") or () if isinstance(r, dict)]
    if routes:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("ROUTE", no_wrap=True)
        table.add_column("RUNS", justify="right")
        table.add_column("SETTLED", justify="right")
        table.add_column("P50", no_wrap=True)
        table.add_column("P90", no_wrap=True)
        table.add_column("<2m", justify="right")
        table.add_column("<5m", justify="right")
        table.add_column("KILLS", justify="right")
        for route in routes:
            table.add_row(
                str(route.get("route") or EMPTY),
                _fmt_int(route.get("runs")),
                _fmt_int(route.get("settled")),
                _fmt_ms(route.get("p50_ms")),
                _fmt_ms(route.get("p90_ms")),
                _fmt_int(route.get("under_2m")),
                _fmt_int(route.get("under_5m")),
                _fmt_int(route.get("kills")),
            )
        console.print("ROUTES")
        console.print(table)
    providers = [p for p in tool.get("providers") or () if isinstance(p, dict)]
    if providers:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("PROVIDER", no_wrap=True)
        table.add_column("RUNS", justify="right")
        table.add_column("OK", justify="right")
        table.add_column("FAIL", justify="right")
        table.add_column("CENS", justify="right")
        table.add_column("P50", no_wrap=True)
        table.add_column("P90", no_wrap=True)
        table.add_column("KILLED", justify="right")
        table.add_column("KHOURS", justify="right")
        for provider in providers:
            outcomes = provider.get("outcomes") or {}
            table.add_row(
                str(provider.get("provider") or EMPTY),
                _fmt_int(provider.get("runs")),
                _fmt_int(outcomes.get("succeeded")),
                _fmt_int(outcomes.get("failed")),
                _fmt_int(outcomes.get("censored")),
                _fmt_ms(provider.get("p50_ms")),
                _fmt_ms(provider.get("p90_ms")),
                _fmt_int(provider.get("kills")),
                _fmt_hours(provider.get("kill_hours")),
            )
        console.print("PROVIDERS")
        console.print(table)
    trend = [b for b in tool.get("trend") or () if isinstance(b, dict)]
    if trend:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("DAY", no_wrap=True)
        table.add_column("RUNS", justify="right")
        table.add_column("OK", justify="right")
        table.add_column("FAIL", justify="right")
        table.add_column("CENS", justify="right")
        table.add_column("KILLED", justify="right")
        table.add_column("MON", justify="right")
        table.add_column("P50", no_wrap=True)
        for bucket in trend:
            table.add_row(
                _format_day(bucket.get("day_start_ts")),
                _fmt_int(bucket.get("runs")),
                _fmt_int(bucket.get("succeeded")),
                _fmt_int(bucket.get("failed")),
                _fmt_int(bucket.get("censored")),
                _fmt_int(bucket.get("killed_at_ceiling")),
                _fmt_int(bucket.get("monitor_owned")),
                _fmt_ms(bucket.get("p50_ms")),
            )
        console.print("TREND")
        console.print(table)


def _print_signal_lines(console: Console, tool: dict[str, Any]) -> None:
    backtest = tool.get("backtest") or {}
    waste = tool.get("waste") or {}
    monitor = tool.get("monitor_owned") or {}
    repeats = tool.get("repeats") or {}
    demand = tool.get("demand") or {}
    predictions = int(backtest.get("predictions") or 0)
    if predictions:
        coverage = _fmt_coverage(backtest.get("coverage"))
        width = _fmt_width(backtest.get("median_width"))
        target_cov = backtest.get("target_coverage", 0.80)
        target_width = backtest.get("target_max_width", 3.0)
        meets = backtest.get("meets_target")
        verdict = (
            "[green]met[/green]"
            if meets is True
            else ("[yellow]not met[/yellow]" if meets is False else EMPTY)
        )
        console.print(
            f"{'backtest':<11}whole run: {coverage} of {predictions:,}"
            f" inside p10\u2013p90 \u00b7 median width {width}"
            f" \u00b7 target \u2265{_fmt_pct_value(target_cov)}"
            f" and \u2264{_fmt_ratio_value(target_width)}: {verdict}"
        )
    else:
        console.print(f"{'backtest':<11}whole run: no predictions (need 20 priors)")
    killed = waste.get("killed_at_ceiling") or {}
    reruns = int(tool.get("reruns_after_kill") or 0)
    killed_runs = int(killed.get("runs") or 0)
    killed_cell = (
        f"killed at ceiling {killed_runs:,}"
        f" ({_fmt_hours_value(killed.get('hours'))};"
        f" {reruns:,} rerun within 30m)"
        if killed_runs
        else "killed at ceiling 0"
    )
    console.print(
        f"{'waste':<11}{killed_cell}"
        f" \u00b7 {_fmt_waste_cell('timeout', waste.get('timeout'))}"
        f" \u00b7 {_fmt_waste_cell('stopped', waste.get('stopped'))}"
        f" \u00b7 {_fmt_waste_cell('lost', waste.get('lost'), show_without=True)}"
        f" \u00b7 {_fmt_waste_cell('interrupted', waste.get('interrupted'))}"
        f" \u00b7 {_fmt_waste_cell('other signals', waste.get('other_signal'))}"
    )
    share = monitor.get("under_2m_share")
    share_text = (
        f" ({_fmt_pct_value(share)})" if isinstance(share, (int, float)) else ""
    )
    console.print(
        f"{'routes':<11}monitor-owned {_fmt_int(monitor.get('runs'))}"
        f" \u00b7 finished under 2m: {_fmt_int(monitor.get('under_2m'))}{share_text}"
        f" \u00b7 under 5m: {_fmt_int(monitor.get('under_5m'))}"
    )
    console.print(
        f"{'repeats':<11}{_fmt_int(repeats.get('repeat_runs'))} exact repeats"
        f" ({_fmt_hours(repeats.get('repeat_hours'))};"
        f" {_fmt_int(repeats.get('after_censored_runs'))} after a censored run)"
        f" \u00b7 {_fmt_int(repeats.get('duplicate_runs'))} concurrent duplicates"
        f" ({_fmt_hours(repeats.get('duplicate_hours'))})"
        f" \u00b7 {_fmt_int(repeats.get('unkeyed_runs'))} unkeyed"
        f" \u00b7 content-equivalent: sase tool receipts"
    )
    cpu_p50 = _fmt_cpu_seconds(demand.get("cpu_seconds_p50"))
    cores = demand.get("effective_cores_p50")
    cores_text = f"{cores:.1f} cores" if isinstance(cores, (int, float)) else EMPTY
    token_runs = int(demand.get("token_wait_runs") or 0)
    timeouts = int(demand.get("token_wait_timeouts") or 0)
    console.print(
        f"{'demand':<11}{_fmt_int(demand.get('runs_with_usage'))} runs with usage"
        f" \u00b7 CPU p50 {cpu_p50} ({cores_text})"
        f" \u00b7 max process RSS p90 {format_kib(_as_int(demand.get('max_process_rss_kib_p90')))}"
        f" \u00b7 tree RSS peak p90 {format_kib(_as_int(demand.get('peak_tree_rss_kib_p90')))}"
        f" \u00b7 pytest grants in {_fmt_int(demand.get('runs_with_grants'))} runs,"
        f" width p50 {_fmt_int(demand.get('grant_width_p50'))}"
        f" / p90 {_fmt_int(demand.get('grant_width_p90'))}"
        f" \u00b7 token waits {token_runs:,} runs"
        f" ({_fmt_ms(demand.get('token_wait_ms_total'))}, {timeouts:,} timeouts)"
    )


def _fmt_waste_cell(name: str, cell: object, *, show_without: bool = False) -> str:
    if not isinstance(cell, dict):
        return f"{name} 0"
    runs = int(cell.get("runs") or 0)
    if not runs:
        return f"{name} 0"
    text = f"{name} {runs:,} ({_fmt_hours_value(cell.get('hours'))}"
    if show_without:
        text += f"; {int(cell.get('runs_without_duration') or 0):,} without duration"
    return text + ")"


def _format_since(since_ts: object) -> str:
    if type(since_ts) is bool or not isinstance(since_ts, (int, float)):
        return EMPTY
    return datetime.fromtimestamp(int(since_ts)).strftime("%m-%d")


def _format_day(day_start_ts: object) -> str:
    if type(day_start_ts) is bool or not isinstance(day_start_ts, (int, float)):
        return EMPTY
    return datetime.fromtimestamp(int(day_start_ts)).strftime("%m-%d")


def _fmt_int(value: object) -> str:
    if type(value) is bool or not isinstance(value, int):
        return EMPTY
    return f"{value:,}"


def _as_int(value: object) -> int | None:
    if type(value) is bool or not isinstance(value, int):
        return None
    return value


def _fmt_ms(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return format_duration_ms(int(value))


def _fmt_hours(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.1f}h"


def _fmt_hours_value(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.1f}h"


def _fmt_share(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value * 100:.1f}%"


def _fmt_pct_value(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value * 100:.0f}%"


def _fmt_num(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.1f}"


def _fmt_ratio(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.1f}\u00d7"


def _fmt_ratio_value(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.0f}\u00d7"


def _fmt_coverage(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value * 100:.0f}%"


def _fmt_width(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return f"{value:.1f}\u00d7"


def _fmt_cpu_seconds(value: object) -> str:
    if type(value) is bool or not isinstance(value, (int, float)):
        return EMPTY
    return _fmt_ms(int(value * 1000))


__all__ = ["ToolStatsCliRequest", "handle_stats"]
