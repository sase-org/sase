"""``sase agent load`` — show this machine's runner capacity.

The command renders the shared capacity view model
(:mod:`sase.core.runner_slots._capacity_view`) built from the authoritative
machine report, so the CLI, ``sase agent list -j``, and the TUI chip all
agree. ``-j`` prints the exact report; the default output is colored Rich.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

ReportFn = Callable[..., Any]


def handle_agents_load(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    report_fn: ReportFn | None = None,
) -> None:
    """Render this machine's runner capacity (pretty by default, JSON with -j)."""
    force_rescan = bool(getattr(args, "rescan", False))
    as_json = bool(getattr(args, "json", False))

    report = _load_report(force_rescan=force_rescan, report_fn=report_fn)
    if as_json:
        json.dump(_report_to_json_dict(report), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    from sase.core.runner_slots import capacity_view

    _render_load_view(
        capacity_view(report), machine=str(report.machine), console=console
    )


def _load_report(*, force_rescan: bool, report_fn: ReportFn | None) -> Any:
    if report_fn is not None:
        return report_fn(force_rescan=force_rescan)
    from sase.core.runner_slots import machine_capacity_report

    return machine_capacity_report(force_rescan=force_rescan)


def _report_to_json_dict(report: Any) -> dict[str, Any]:
    """Keep the CLI's stable JSON payload aligned with every report consumer."""
    from sase.core.runner_slots import machine_capacity_report_to_json_dict

    return machine_capacity_report_to_json_dict(report)


def _render_load_view(
    view: Any, *, machine: str, console: Console | None = None
) -> None:
    """Render one capacity view model as colored Rich sections."""
    out = console or Console()
    out.print(_summary_text(view))
    if view.over_limit_note is not None:
        out.print(Text(f"▲ {view.over_limit_note}", style="bold red"))
    if view.accounting_unavailable:
        out.print(
            Text(
                "capacity accounting unavailable: the core is too old to "
                "explain who holds capacity — totals only",
                style="bold yellow",
            )
        )
    if view.admission_blocked:
        out.print(
            Text(
                "admission blocked: the capacity snapshot is invalid — "
                "occupied units are a known subtotal, not free capacity",
                style="bold red",
            )
        )
    out.print(_holdings_table(view))
    if view.riders:
        out.print(_riders_text(view))
    out.print(_idle_text(view))
    out.print(_queued_text(view))
    if view.diagnostics:
        out.print(_diagnostics_panel(view))
    out.print(
        Text(
            f"Capacity on {machine} · sase agent load -j for the exact report",
            style="dim",
        )
    )


def _summary_text(view: Any) -> Text:
    text = Text()
    if view.over_limit_note is not None:
        text.append(view.headline, style="bold red")
    elif view.admission_blocked:
        text.append(view.headline, style="bold yellow")
    else:
        text.append(view.headline, style="bold green")
    text.append("\n")
    text.append(view.limit_line, style="dim")
    text.append("\n")
    text.append(view.snapshot_line, style="dim")
    if view.running_line is not None:
        text.append("\n")
        text.append(view.running_line, style="dim")
    return text


def _holdings_table(view: Any) -> Panel:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("NAME", style="bold")
    table.add_column("KIND")
    table.add_column("CHARGED", justify="right")
    table.add_column("SOURCE")
    table.add_column("SINCE")
    table.add_column("BUDGET", justify="right")
    for row in view.holdings:
        table.add_row(
            row.name,
            row.kind,
            _fmt(row.charged_weight),
            row.weight_source,
            _date(row.since),
            f"c{row.authored_budget}" if row.authored_budget is not None else "-",
        )
    table.add_row(
        "total",
        "",
        _fmt(view.total_charged),
        "",
        "",
        "",
        style="bold",
    )
    title = f"Holding capacity ({len(view.holdings)})"
    if not view.holdings:
        table.add_row("-", "nothing holds capacity", "-", "-", "-", "-")
    return Panel(table, title=title, border_style="cyan")


def _riders_text(view: Any) -> Text:
    text = Text("Shared claims ride along:\n", style="bold")
    for rider in view.riders:
        text.append(f"  {rider.name}", style="bold")
        text.append(f" — shared with {rider.holder_name}\n", style="dim")
    return text


def _idle_text(view: Any) -> Panel | Text:
    if not view.idle_groups:
        return Text("Live, holding nothing: none", style="dim")
    text = Text()
    for group in view.idle_groups:
        text.append(f"{group.reason_label} ({group.count}): ", style="bold")
        text.append(", ".join(group.members))
        if group.truncated:
            text.append(f" · +{group.hidden} more", style="dim")
        text.append("\n")
    rendered = Text(str(text).rstrip("\n"))
    return Panel(
        rendered,
        title="Live, holding nothing",
        border_style="cyan",
    )


def _queued_text(view: Any) -> Panel | Text:
    if not view.queued:
        return Text("Queued for capacity: none", style="dim")
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("QUEUE", justify="right")
    table.add_column("NAME", style="bold")
    table.add_column("BLOCKER")
    for row in view.queued:
        blocker_style = "green" if row.eligible else ""
        table.add_row(
            f"#{row.queue_position}",
            row.name,
            Text(row.blocker, style=blocker_style),
        )
    return Panel(table, title=f"Queued for capacity ({len(view.queued)})")


def _diagnostics_panel(view: Any) -> Panel:
    text = Text()
    for line in view.diagnostics:
        text.append(f"• {line}\n")
    if view.admission_blocked:
        text.append("admission blocked\n", style="bold red")
    return Panel(Text(str(text).rstrip("\n")), title="Diagnostics")


def _date(value: str | None) -> str:
    if not value:
        return "-"
    return value[:10]


def _fmt(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"
