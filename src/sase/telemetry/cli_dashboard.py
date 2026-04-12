"""``sase telemetry dashboard`` — live auto-refreshing TUI dashboard.

Supports two modes:

- **Summary mode** (default): styled stat panels with color-coded gauges
  and compact subsystem metric tables.
- **Charts mode** (``-c/--charts``): historical line/bar charts powered
  by Prometheus range queries rendered via plotext.
"""

from __future__ import annotations

import argparse
import time

from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.telemetry._config import get_telemetry_config
from sase.telemetry.catalog import SUBSYSTEM_ORDER, get_subsystems
from sase.telemetry.scrape import (
    MetricSample,
    check_reachable,
    compute_percentiles,
    scrape,
)

# ── Time-range helpers ───────────────────────────────────────────────

_RANGE_SECONDS: dict[str, int] = {
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "7d": 604800,
}

_STEP_FOR_RANGE: dict[str, str] = {
    "1h": "15s",
    "6h": "60s",
    "24h": "300s",
    "7d": "1800s",
}

_RATE_WINDOW_FOR_RANGE: dict[str, str] = {
    "1h": "15m",
    "6h": "1h",
    "24h": "4h",
    "7d": "1d",
}

# ── Color thresholds for stat panels ────────────────────────────────

_GAUGE_STYLES: list[tuple[float, str]] = [
    (0, "green"),
    (5, "yellow"),
    (10, "red"),
]


def _gauge_style(value: float) -> str:
    """Return a Rich style string based on gauge value thresholds."""
    style = "green"
    for threshold, s in _GAUGE_STYLES:
        if value >= threshold:
            style = s
    return style


# ── Data source resolution ──────────────────────────────────────────


def _resolve_source(source: str) -> str | None:
    """Resolve the data source URL, returning None if unreachable."""
    cfg = get_telemetry_config()
    pushgateway_url = f"http://{cfg.pushgateway_url}/metrics"
    exposition_url = f"http://localhost:{cfg.exposition_port}/metrics"

    if source == "pushgateway":
        return pushgateway_url if check_reachable(pushgateway_url) else None
    if source == "exposition":
        return exposition_url if check_reachable(exposition_url) else None

    if check_reachable(pushgateway_url):
        return pushgateway_url
    if check_reachable(exposition_url):
        return exposition_url
    return None


# ── Summary mode (enhanced) ─────────────────────────────────────────


def _group_samples_by_subsystem(
    samples: list[MetricSample],
) -> dict[str, list[MetricSample]]:
    """Group samples by subsystem using the catalog."""
    subsystems = get_subsystems()
    name_to_sub: dict[str, str] = {}
    for sub_name, metrics in subsystems.items():
        for m in metrics:
            name_to_sub[m.prometheus_name] = sub_name
            for suffix in ("_total", "_bucket", "_count", "_sum", "_created"):
                name_to_sub[m.prometheus_name + suffix] = sub_name

    grouped: dict[str, list[MetricSample]] = {}
    for s in samples:
        sub = name_to_sub.get(s.name)
        if sub:
            grouped.setdefault(sub, []).append(s)
    return grouped


def _pick_key_metrics(
    samples: list[MetricSample],
) -> list[tuple[str, str]]:
    """Extract compact key metric rows from a subsystem's samples.

    Returns (label, value_str) pairs for display in the dashboard panel.
    """
    bucket_groups: dict[str, list[MetricSample]] = {}
    regular: list[MetricSample] = []

    for s in samples:
        if s.name.endswith("_bucket"):
            base = s.name[: -len("_bucket")]
            bucket_groups.setdefault(base, []).append(s)
        elif s.name.endswith(("_count", "_sum", "_created")):
            continue
        else:
            regular.append(s)

    aggregated: dict[str, float] = {}
    for s in regular:
        base = s.name.removesuffix("_total")
        aggregated[base] = aggregated.get(base, 0) + s.value

    rows: list[tuple[str, str]] = []
    for base, total in aggregated.items():
        short = base.removeprefix("sase_").replace("_", " ").title()
        rows.append((short, f"{total:g}"))

    for base, buckets in bucket_groups.items():
        pcts = compute_percentiles(buckets)
        if pcts:
            short = base.removeprefix("sase_").replace("_", " ").title()
            pct_str = " ".join(f"{k}={v:g}s" for k, v in pcts.items())
            rows.append((short, pct_str))

    return rows


# ── Key gauge stat cards ────────────────────────────────────────────

_KEY_GAUGES = [
    ("sase_agent_active", "Active Agents"),
    ("sase_workspace_active", "Active Workspaces"),
    ("sase_bead_active", "Active Beads"),
]


def _build_stat_panels(samples: list[MetricSample]) -> list[Panel]:
    """Build large styled stat panels for key gauges with sparklines."""
    from sase.telemetry.charts import render_sparkline

    sample_map: dict[str, float] = {}
    for s in samples:
        base = s.name.removesuffix("_total")
        sample_map[base] = sample_map.get(base, 0) + s.value

    panels: list[Panel] = []
    for metric_name, display_name in _KEY_GAUGES:
        value = sample_map.get(metric_name, 0)
        style = _gauge_style(value)
        spark = render_sparkline([value] * 8, title="")
        content = Group(
            Text(f"{value:g}", style=f"bold {style}", justify="center"),
            spark,
        )
        panels.append(
            Panel(
                content,
                title=f"[bold]{display_name}[/bold]",
                border_style=style,
                width=24,
                height=6,
                padding=(0, 2),
            )
        )
    return panels


def _build_subsystem_panel(name: str, rows: list[tuple[str, str]]) -> Panel:
    """Build a compact Rich panel for one subsystem."""
    table = Table(show_header=False, box=None, pad_edge=False, expand=True)
    table.add_column("Metric", style="bold", ratio=1)
    table.add_column("Value", justify="right", ratio=1)
    for label, value in rows:
        style = ""
        try:
            v = float(value.split("=")[0] if "=" in value else value)
            if v > 100:
                style = "yellow"
            if v > 500:
                style = "red"
        except ValueError:
            pass
        table.add_row(label, Text(value, style=style))
    return Panel(table, title=name, border_style="cyan", width=36)


def _build_dashboard(samples: list[MetricSample]) -> Group:
    """Build the full summary-mode dashboard layout.

    Exposed for testing — returns a Rich renderable.
    """
    stat_panels = _build_stat_panels(samples)
    stat_row = Columns(stat_panels, equal=True, expand=False)

    grouped = _group_samples_by_subsystem(samples)
    subsystem_panels: list[Panel] = []
    for sub_name in SUBSYSTEM_ORDER:
        sub_samples = grouped.get(sub_name)
        if not sub_samples:
            continue
        rows = _pick_key_metrics(sub_samples)
        if rows:
            subsystem_panels.append(_build_subsystem_panel(sub_name, rows))

    metric_rows = Columns(subsystem_panels, equal=True, expand=True)
    return Group(stat_row, Text(""), metric_rows)


# ── Charts mode ─────────────────────────────────────────────────────


def _get_chart_specs(
    rate_window: str,
) -> list[tuple[str, list[str], str, list[str]]]:
    """Return chart specs with the given rate window interpolated into PromQL queries."""
    w = rate_window
    return [
        (
            "Agent Run Duration",
            [
                f"histogram_quantile(0.50, sum(rate(sase_agent_run_duration_seconds_bucket[{w}])) by (le))",
                f"histogram_quantile(0.95, sum(rate(sase_agent_run_duration_seconds_bucket[{w}])) by (le))",
            ],
            "seconds",
            ["p50", "p95"],
        ),
        (
            "Active Agents",
            ["sase_agent_active"],
            "agents",
            ["active"],
        ),
        (
            "Agent Throughput",
            [
                f'rate(sase_agent_runs_total{{status="ok"}}[{w}])',
                f'rate(sase_agent_runs_total{{status="error"}}[{w}])',
            ],
            "runs/sec",
            ["ok", "error"],
        ),
        (
            "LLM Token Usage",
            [
                f"rate(sase_llm_input_tokens_total[{w}])",
                f"rate(sase_llm_output_tokens_total[{w}])",
                f"rate(sase_llm_cache_read_tokens_total[{w}])",
            ],
            "tokens/sec",
            ["input", "output", "cache"],
        ),
        (
            "LLM Latency",
            [
                f"histogram_quantile(0.50, sum(rate(sase_llm_invocation_duration_seconds_bucket[{w}])) by (le))",
                f"histogram_quantile(0.95, sum(rate(sase_llm_invocation_duration_seconds_bucket[{w}])) by (le))",
            ],
            "seconds",
            ["p50", "p95"],
        ),
        (
            "Error Rate",
            [
                f'rate(sase_agent_runs_total{{status="error"}}[{w}])',
                f"rate(sase_llm_errors_total[{w}])",
            ],
            "errors/sec",
            ["agent errors", "LLM errors"],
        ),
    ]


def _build_charts_dashboard(
    prom_url: str,
    range_key: str,
    subsystem_filter: str | None,
    width: int,
) -> Group:
    """Build the charts-mode dashboard by querying Prometheus."""
    from sase.telemetry.charts import render_bar_chart, render_line_chart
    from sase.telemetry.prom_query import TimeSeries, query_range

    range_secs = _RANGE_SECONDS.get(range_key, 3600)
    step = _STEP_FOR_RANGE.get(range_key, "15s")
    rate_window = _RATE_WINDOW_FOR_RANGE.get(range_key, "15m")
    end = time.time()
    start = end - range_secs

    all_specs = _get_chart_specs(rate_window)
    specs = all_specs
    if subsystem_filter:
        lf = subsystem_filter.lower()
        specs = [s for s in all_specs if lf in s[0].lower()]
        if not specs:
            specs = all_specs

    chart_width = max(30, (width - 6) // 2)
    chart_height = 14

    panels: list[Panel] = []
    for title, queries, y_label, legend_labels in specs:
        all_series: list[TimeSeries] = []
        for q in queries:
            result = query_range(prom_url, q, start, end, step)
            if result:
                all_series.append(result[0])
            else:
                all_series.append(TimeSeries(metric=""))

        # Use bar chart for throughput metrics.
        if title == "Agent Throughput":
            bar_labels = legend_labels
            bar_values = [
                sum(p[1] for p in ts.points) / max(len(ts.points), 1)
                for ts in all_series
            ]
            panel = render_bar_chart(
                bar_labels,
                bar_values,
                title=title,
                width=chart_width,
                height=chart_height,
            )
        else:
            panel = render_line_chart(
                all_series,
                title=title,
                y_label=y_label,
                width=chart_width,
                height=chart_height,
                legend_labels=legend_labels,
            )
        panels.append(panel)

    chart_grid = Columns(panels, equal=True, expand=True, column_first=True)

    range_label = Text.assemble(
        ("Range: ", "dim"),
        (range_key, "cyan bold"),
        ("  |  Step: ", "dim"),
        (step, "cyan bold"),
    )

    return Group(range_label, Text(""), chart_grid)


# ── Main handler ────────────────────────────────────────────────────


def handle_telemetry_dashboard(args: argparse.Namespace) -> None:
    """Live auto-refreshing telemetry dashboard."""
    source: str = getattr(args, "source", "auto")
    interval: int = getattr(args, "interval", 5)
    charts_mode: bool = getattr(args, "charts", False)
    range_key: str = getattr(args, "range", "1h")
    subsystem_filter: str | None = getattr(args, "subsystem", None)
    console = Console()
    prom_url: str = ""
    url: str = ""

    # Charts mode: check Prometheus first, fall back to summary mode.
    if charts_mode:
        from sase.telemetry.prom_query import check_prometheus_reachable

        cfg = get_telemetry_config()
        prom_url = f"http://{cfg.prometheus_url}"

        if not check_prometheus_reachable(prom_url):
            console.print(
                "[yellow]Prometheus is not reachable — falling back to summary mode.[/yellow]"
            )
            charts_mode = False
        else:
            interval = max(interval, 15)

    if not charts_mode:
        resolved = _resolve_source(source)
        if resolved is None:
            console.print(
                "[red]No metric source is reachable.[/red]\n"
                "[dim]Run 'sase telemetry status' for diagnostics.[/dim]"
            )
            return
        url = resolved

    mode_label = "charts" if charts_mode else "summary"
    header = Text.assemble(
        ("Telemetry Dashboard", "bold"),
        (" [", "dim"),
        (mode_label, "cyan"),
        ("]", "dim"),
        (" — refreshing every ", ""),
        (f"{interval}s", "cyan"),
        (" — ", ""),
        ("Ctrl+C to exit", "dim"),
    )

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                if charts_mode:
                    layout = _build_charts_dashboard(
                        prom_url,
                        range_key,
                        subsystem_filter,
                        console.width,
                    )
                else:
                    samples = scrape(url)
                    layout = _build_dashboard(samples)
                live.update(Group(header, Text(""), layout))
                time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard stopped.[/dim]")
