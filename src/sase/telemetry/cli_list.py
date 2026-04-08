"""``sase telemetry list`` — metric catalog display."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.telemetry.catalog import MetricInfo, get_subsystems

_KIND_STYLES: dict[str, str] = {
    "counter": "cyan",
    "histogram": "magenta",
    "gauge": "yellow",
}


def handle_telemetry_list(args: argparse.Namespace) -> None:
    """Render the metric catalog grouped by subsystem."""
    subsystem_filter: str | None = getattr(args, "subsystem", None)
    type_filter: str | None = getattr(args, "type", None)

    subsystems = get_subsystems()
    console = Console()
    printed = False

    for subsystem_name, metrics in subsystems.items():
        if subsystem_filter and subsystem_filter.lower() != subsystem_name.lower():
            continue

        filtered: list[MetricInfo] = metrics
        if type_filter:
            filtered = [m for m in metrics if m.kind == type_filter]
        if not filtered:
            continue

        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("Name", style="bold")
        table.add_column("Prometheus Name")
        table.add_column("Type")
        table.add_column("Labels")

        for m in filtered:
            kind_badge = Text(m.kind, style=_KIND_STYLES.get(m.kind, ""))
            labels_str = ", ".join(m.labels) if m.labels else "-"
            table.add_row(m.attr, m.prometheus_name, kind_badge, labels_str)

        title = f"{subsystem_name} ({len(filtered)} metric{'s' if len(filtered) != 1 else ''})"
        panel = Panel(table, title=title, border_style="cyan")
        console.print(panel)
        printed = True

    if not printed:
        console.print("[dim]No metrics match the given filters.[/dim]")
