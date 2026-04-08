"""``sase telemetry snapshot`` — fetch and display current metric values."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.telemetry._config import get_telemetry_config
from sase.telemetry.catalog import MetricInfo, get_subsystems
from sase.telemetry.scrape import (
    MetricSample,
    check_reachable,
    compute_percentiles,
    format_samples_as_json,
    format_samples_as_prometheus,
    scrape,
)

_KIND_STYLES: dict[str, str] = {
    "counter": "cyan",
    "histogram": "magenta",
    "gauge": "yellow",
}


def _resolve_source(source: str) -> str | None:
    """Resolve the data source URL, returning None if unreachable.

    For "auto", tries pushgateway first, then exposition.
    """
    cfg = get_telemetry_config()
    pushgateway_url = f"http://{cfg.pushgateway_url}/metrics"
    exposition_url = f"http://localhost:{cfg.exposition_port}/metrics"

    if source == "pushgateway":
        return pushgateway_url if check_reachable(pushgateway_url) else None
    if source == "exposition":
        return exposition_url if check_reachable(exposition_url) else None

    # auto: try pushgateway first, then exposition
    if check_reachable(pushgateway_url):
        return pushgateway_url
    if check_reachable(exposition_url):
        return exposition_url
    return None


def _filter_by_subsystem(
    samples: list[MetricSample],
    subsystems: dict[str, list[MetricInfo]],
    subsystem_filter: str,
) -> list[MetricSample]:
    """Filter samples to those belonging to a specific subsystem."""
    target_names: set[str] = set()
    for name, metrics in subsystems.items():
        if name.lower() == subsystem_filter.lower():
            for m in metrics:
                target_names.add(m.prometheus_name)
            break
    if not target_names:
        return []

    # Include histogram sub-metrics (_bucket, _count, _sum, _total, _created)
    expanded: set[str] = set()
    for base in target_names:
        expanded.add(base)
        for suffix in ("_total", "_bucket", "_count", "_sum", "_created"):
            expanded.add(base + suffix)

    return [s for s in samples if s.name in expanded]


def _group_samples_by_subsystem(
    samples: list[MetricSample],
    subsystems: dict[str, list[MetricInfo]],
) -> dict[str, list[MetricSample]]:
    """Group samples by their subsystem using the catalog."""
    # Build name -> subsystem mapping (including suffixed variants)
    name_to_subsystem: dict[str, str] = {}
    for subsystem_name, metrics in subsystems.items():
        for m in metrics:
            name_to_subsystem[m.prometheus_name] = subsystem_name
            for suffix in ("_total", "_bucket", "_count", "_sum", "_created"):
                name_to_subsystem[m.prometheus_name + suffix] = subsystem_name

    grouped: dict[str, list[MetricSample]] = {}
    for s in samples:
        sub = name_to_subsystem.get(s.name)
        if sub:
            grouped.setdefault(sub, []).append(s)

    return grouped


def _render_rich(samples: list[MetricSample], subsystem_filter: str | None) -> None:
    """Render samples as Rich panels grouped by subsystem."""
    console = Console()
    subsystems = get_subsystems()

    if subsystem_filter:
        filtered = _filter_by_subsystem(samples, subsystems, subsystem_filter)
        if not filtered:
            console.print("[dim]No metrics match the given subsystem filter.[/dim]")
            return
        grouped = _group_samples_by_subsystem(filtered, subsystems)
    else:
        grouped = _group_samples_by_subsystem(samples, subsystems)

    if not grouped:
        console.print("[dim]No known metrics found in the scraped data.[/dim]")
        return

    # Render in subsystem order
    from sase.telemetry.catalog import SUBSYSTEM_ORDER

    printed = False
    for subsystem_name in SUBSYSTEM_ORDER:
        sub_samples = grouped.get(subsystem_name)
        if not sub_samples:
            continue

        # Separate histogram buckets from regular samples for percentile display
        bucket_groups: dict[str, list[MetricSample]] = {}
        regular: list[MetricSample] = []

        for s in sub_samples:
            if s.name.endswith("_bucket"):
                base = s.name[: -len("_bucket")]
                bucket_groups.setdefault(base, []).append(s)
            elif s.name.endswith(("_count", "_sum", "_created")):
                # Skip histogram helper metrics from the display table
                continue
            else:
                regular.append(s)

        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        table.add_column("Type")

        for s in regular:
            kind_badge = Text(s.metric_type, style=_KIND_STYLES.get(s.metric_type, ""))
            label_str = ""
            if s.labels:
                label_str = (
                    "{" + ",".join(f'{k}="{v}"' for k, v in s.labels.items()) + "}"
                )
            display_name = s.name + label_str
            table.add_row(display_name, f"{s.value:g}", kind_badge)

        # Add percentile rows for histograms
        for base, buckets in bucket_groups.items():
            pcts = compute_percentiles(buckets)
            if pcts:
                pct_parts = " ".join(f"{k}={v:g}s" for k, v in pcts.items())
                table.add_row(
                    base,
                    f"({pct_parts})",
                    Text("histogram", style="magenta"),
                )

        count = len(regular) + len(bucket_groups)
        title = f"{subsystem_name} ({count} metric{'s' if count != 1 else ''})"
        panel = Panel(table, title=title, border_style="cyan")
        console.print(panel)
        printed = True

    # Handle samples not in any known subsystem
    remaining = grouped.get("Other")
    if remaining:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        table.add_column("Type")
        for s in remaining:
            kind_badge = Text(s.metric_type, style=_KIND_STYLES.get(s.metric_type, ""))
            table.add_row(s.name, f"{s.value:g}", kind_badge)
        panel = Panel(table, title="Other", border_style="cyan")
        console.print(panel)
        printed = True

    if not printed:
        console.print("[dim]No known metrics found in the scraped data.[/dim]")


def handle_telemetry_snapshot(args: argparse.Namespace) -> None:
    """Fetch and display current metric values."""
    source: str = getattr(args, "source", "auto")
    fmt: str = getattr(args, "format", "rich")
    subsystem_filter: str | None = getattr(args, "subsystem", None)

    console = Console()

    url = _resolve_source(source)
    if url is None:
        console.print(
            "[red]No metric source is reachable.[/red]\n"
            "[dim]Run 'sase telemetry status' for diagnostics.[/dim]"
        )
        return

    samples = scrape(url)
    if not samples:
        console.print("[dim]No metrics returned from the source.[/dim]")
        return

    if fmt == "json":
        if subsystem_filter:
            subsystems = get_subsystems()
            samples = _filter_by_subsystem(samples, subsystems, subsystem_filter)
        console.print(format_samples_as_json(samples))
    elif fmt == "prometheus":
        if subsystem_filter:
            subsystems = get_subsystems()
            samples = _filter_by_subsystem(samples, subsystems, subsystem_filter)
        console.print(format_samples_as_prometheus(samples))
    else:
        _render_rich(samples, subsystem_filter)
