"""``sase telemetry dashboard`` — live auto-refreshing TUI dashboard."""

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
    # Separate buckets from regular samples.
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

    # Aggregate counters/gauges by base metric name.
    aggregated: dict[str, float] = {}
    for s in regular:
        base = s.name.removesuffix("_total")
        aggregated[base] = aggregated.get(base, 0) + s.value

    rows: list[tuple[str, str]] = []
    for base, total in aggregated.items():
        # Derive a short label from the metric name.
        short = base.removeprefix("sase_").replace("_", " ").title()
        rows.append((short, f"{total:g}"))

    # Add histogram percentiles.
    for base, buckets in bucket_groups.items():
        pcts = compute_percentiles(buckets)
        if pcts:
            short = base.removeprefix("sase_").replace("_", " ").title()
            pct_str = " ".join(f"{k}={v:g}s" for k, v in pcts.items())
            rows.append((short, pct_str))

    return rows


def _build_subsystem_panel(name: str, rows: list[tuple[str, str]]) -> Panel:
    """Build a compact Rich panel for one subsystem."""
    table = Table(show_header=False, box=None, pad_edge=False, expand=True)
    table.add_column("Metric", style="bold", ratio=1)
    table.add_column("Value", justify="right", ratio=1)
    for label, value in rows:
        table.add_row(label, value)
    return Panel(table, title=name, border_style="cyan", width=30)


def _build_dashboard(samples: list[MetricSample]) -> Columns:
    """Build the full dashboard layout from scraped samples.

    Exposed for testing — returns a Rich renderable.
    """
    grouped = _group_samples_by_subsystem(samples)
    panels: list[Panel] = []
    for sub_name in SUBSYSTEM_ORDER:
        sub_samples = grouped.get(sub_name)
        if not sub_samples:
            continue
        rows = _pick_key_metrics(sub_samples)
        if rows:
            panels.append(_build_subsystem_panel(sub_name, rows))

    return Columns(panels, equal=True, expand=True)


def handle_telemetry_dashboard(args: argparse.Namespace) -> None:
    """Live auto-refreshing telemetry dashboard."""
    source: str = getattr(args, "source", "auto")
    interval: int = getattr(args, "interval", 5)
    console = Console()

    url = _resolve_source(source)
    if url is None:
        console.print(
            "[red]No metric source is reachable.[/red]\n"
            "[dim]Run 'sase telemetry status' for diagnostics.[/dim]"
        )
        return

    header = Text.assemble(
        ("Telemetry Dashboard", "bold"),
        " — refreshing every ",
        (f"{interval}s", "cyan"),
        " — ",
        ("Ctrl+C to exit", "dim"),
    )

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                samples = scrape(url)
                layout = _build_dashboard(samples)
                live.update(Group(header, layout))
                time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard stopped.[/dim]")
