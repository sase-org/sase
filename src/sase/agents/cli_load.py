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
from datetime import UTC, datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.ace.tui.widgets._usage_indicator_palette import (
    usage_percent_color,
    usage_rejected_style,
)
from sase.core.runner_slots import (
    capacity_gauge_cells,
    format_capacity_duration,
)

ReportFn = Callable[..., Any]

_IDLE_PREVIEW = 10
_GAUGE_MAX_WIDTH = 64
_VERDICT_STYLES = {
    "ok": ("✓", "bold green"),
    "tight": ("◔", "bold yellow"),
    "full": ("■", "bold #FF9D57"),
    "over": ("▲", "bold red"),
    "blocked": ("!", "bold red"),
    "unknown": ("?", "bold yellow"),
}
_QUEUE_STYLES = {
    "ready": "green",
    "capacity": "yellow",
    "held": "magenta",
    "never_fits": "red",
    "deferred": "dim",
    "other": "yellow",
}
_WEIGHT_NOTES = {
    "default": "default weight",
    "inherited": "weight inherited from its starter",
    "explicit": "explicit weight",
    "explicit_zero": "explicit zero weight — never charges",
    "invalid": "invalid weight",
}
_INACTIVE_ORDER = ("not_live", "not_agent_record", "done")


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
    out.print(_headline_text(view, machine=machine))
    gauge = _gauge_text(view, width=min(max(out.width - 2, 8), _GAUGE_MAX_WIDTH))
    if gauge is not None:
        out.print(gauge)
    out.print(_verdict_text(view))
    out.print(_facts_text(view))
    if view.accounting_unavailable:
        out.print(
            Text(
                "This sase-core build reports totals only.",
                style="bold yellow",
            )
        )
    else:
        attention = _attention_text(view)
        if attention is not None:
            out.print(attention)
        out.print(_charged_table(view))
        out.print(_queued_text(view))
        zero = _zero_weight_text(view)
        if zero is not None:
            out.print(zero)
        waiting = _waiting_text(view)
        if waiting is not None:
            out.print(waiting)
        ignored = _ignored_inactive_text(view)
        if ignored is not None:
            out.print(ignored)
    if view.diagnostics:
        out.print(_diagnostics_panel(view))
    out.print(
        Text(
            f"Capacity on {machine} · sase agent load -j for the exact report",
            style="dim",
        )
    )


def _headline_text(view: Any, *, machine: str) -> Text:
    occupied = _fmt(view.occupied)
    limit = _fmt(view.limit)
    text = Text(f"{machine} · ", style="bold")
    text.append(f"{occupied} / {limit} units in use", style="bold")
    if view.admission_blocked:
        free_label = "? free"
        free_style = "bold yellow"
    elif view.occupied > view.limit:
        free_label = f"{_fmt(view.occupied - view.limit)} over"
        free_style = "bold red"
    else:
        free_label = f"{_fmt(max(0.0, view.free))} free"
        free_style = "bold green"
    text.append(" · ")
    text.append(free_label, style=free_style)
    return text


def _gauge_text(view: Any, *, width: int) -> Text | None:
    cells = capacity_gauge_cells(view, width)
    if not cells:
        return None
    free_percent = 0.0 if view.limit <= 0 else max(0.0, view.free / view.limit * 100.0)
    fill = f"bold {usage_percent_color(free_percent, dark=True)}"
    rejected = usage_rejected_style(dark=True)
    styles = {
        "used": rejected if view.admission_blocked else fill,
        "over": rejected,
        "unknown": rejected,
        "limit": rejected,
        "free": "dim",
        "gap": "",
        "beyond": "",
    }
    text = Text()
    run_style: str | None = None
    run_chars: list[str] = []
    for cell in cells:
        current = styles.get(cell.kind, "")
        if run_style is not None and current != run_style:
            text.append("".join(run_chars), style=run_style or None)
            run_chars.clear()
        run_style = current
        run_chars.append(cell.char)
    if run_chars:
        text.append("".join(run_chars), style=run_style or None)
    return text


def _verdict_text(view: Any) -> Text:
    verdict = view.verdict
    if verdict is None:
        return Text(
            "? Holder accounting unavailable — totals only", style="bold yellow"
        )
    glyph, style = _VERDICT_STYLES.get(verdict.tone, ("?", "bold yellow"))
    text = Text(f"{glyph} {verdict.title}", style=style)
    if verdict.detail:
        text.append(f"\n  {verdict.detail}", style="dim")
    return text


def _facts_text(view: Any) -> Text:
    parts = [_limit_provenance(view)]
    stamp = _timestamp(float(view.computed_at))
    age = format_capacity_duration(view.scan_age_seconds)
    parts.append(f"report {stamp} · scan {age} old")
    if not view.scan_current:
        parts.append("records changed since scan")
    return Text(" · ".join(parts), style="dim")


def _limit_provenance(view: Any) -> str:
    info = view.limit_info
    parts = [f"limit {_fmt(view.limit)}"]
    if info is not None and info.override_source is not None:
        age = max(0.0, float(info.override_age_seconds or 0.0))
        warning = " ⚠" if info.override_long_lived else ""
        config = (
            f" (config {_fmt(info.configured)})" if info.configured is not None else ""
        )
        duration = _override_age(age)
        parts.append(f"{info.override_source} override for {duration}{warning}{config}")
    elif info is not None and info.configured is not None:
        parts.append(f"from config {_fmt(info.configured)}")
    return " · ".join(parts)


def _attention_text(view: Any) -> Panel | None:
    if not view.attention_groups and not view.diagnostics:
        return None
    text = Text()
    for group in view.attention_groups:
        for name in group.members:
            text.append("▱? ", style="yellow")
            text.append(name, style="bold yellow")
            text.append(f"  {group.reason_label}\n", style="dim")
    for line in view.diagnostics:
        text.append(f"• {line}\n", style="yellow")
    return Panel(
        _rstrip_text(text),
        title="Needs attention",
        border_style="yellow",
    )


def _charged_table(view: Any) -> Panel:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("UNITS", justify="right")
    table.add_column("NAME", style="bold")
    table.add_column("KIND")
    table.add_column("RUNNING", justify="right")
    table.add_column("NOTE")
    charged = tuple(view.charged)
    for row in charged:
        table.add_row(
            _fmt(row.charged_weight),
            row.name,
            row.kind,
            format_capacity_duration(row.running_seconds),
            _holding_note(row),
        )
    title = (
        f"Using capacity ({_fmt(view.total_charged)} units · "
        f"{len(charged)} {'agent' if len(charged) == 1 else 'agents'})"
    )
    if not charged:
        table.add_row(
            "-",
            _empty_charged_message(view),
            "",
            "",
            "",
        )
    return Panel(table, title=title, border_style="cyan")


def _queued_text(view: Any) -> Panel | Text:
    queued = tuple(view.queued)
    if not queued:
        return Text("Queued for capacity (0): Nobody is queued", style="dim")
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("#", justify="right")
    table.add_column("NAME", style="bold")
    table.add_column("REQUESTS", justify="right")
    table.add_column("WAITING", justify="right")
    table.add_column("BLOCKER")
    for row in queued:
        table.add_row(
            f"#{row.queue_position}",
            row.name,
            _fmt(row.requested_weight),
            format_capacity_duration(row.waiting_seconds),
            Text(row.blocker, style=_QUEUE_STYLES.get(row.tone, "yellow")),
        )
    return Panel(table, title=f"Queued for capacity ({len(queued)})")


def _zero_weight_text(view: Any) -> Text | None:
    rows = tuple(view.zero_weight)
    riders = tuple(view.riders)
    if not rows and not riders:
        return None
    text = Text("Running at zero weight\n", style="bold")
    for row in rows:
        text.append("▰0 ", style="dim")
        text.append(f"{row.name}", style="bold")
        text.append(
            f"  {row.kind}  {format_capacity_duration(row.running_seconds)}  "
            f"{_holding_note(row)}\n",
            style="dim",
        )
    for rider in riders:
        text.append("⇢  ", style="bold")
        text.append(rider.name, style="bold")
        text.append(
            f"  rider  {format_capacity_duration(rider.running_seconds)}  "
            f"shares {rider.holder_name}'s claim\n",
            style="dim",
        )
    return _rstrip_text(text)


def _waiting_text(view: Any) -> Text | None:
    groups = tuple(view.waiting_groups)
    if not groups:
        return None
    text = Text("Not running\n", style="bold")
    for group in groups:
        preview = list(group.members[:_IDLE_PREVIEW])
        hidden = group.count - len(preview)
        text.append(f"{group.reason_label} ({group.count}): ", style="bold")
        text.append(", ".join(preview))
        if hidden:
            text.append(f" · +{hidden} more", style="dim")
        text.append("\n")
    return _rstrip_text(text)


def _ignored_inactive_text(view: Any) -> Text | None:
    groups = {group.reason_code: group for group in view.inactive_groups}
    total = sum(group.count for group in view.inactive_groups)
    if total <= 0:
        return None
    bits: list[str] = []
    for code in _INACTIVE_ORDER:
        group = groups.pop(code, None)
        if group is None:
            continue
        bits.append(f"{group.count} {group.reason_label}")
    for code in sorted(groups):
        group = groups[code]
        bits.append(f"{group.count} {group.reason_label}")
    detail = " · ".join(bits)
    return Text(
        f"Ignored {total} inactive records: {detail} (sase agent load -j lists them)",
        style="dim",
    )


def _diagnostics_panel(view: Any) -> Panel:
    text = Text()
    for line in view.diagnostics:
        text.append(f"• {line}\n")
    if view.admission_blocked:
        text.append("admission blocked\n", style="bold red")
    return Panel(_rstrip_text(text), title="Diagnostics")


def _holding_note(row: Any) -> str:
    parts: list[str] = []
    source = _WEIGHT_NOTES.get(str(row.weight_source))
    if source:
        parts.append(source)
    if row.authored_budget is not None:
        parts.append(f"budget {row.authored_budget}")
    riders = tuple(getattr(row, "rider_names", ()) or ())
    if riders:
        noun = "rider" if len(riders) == 1 else "riders"
        parts.append(f"+{len(riders)} {noun}")
    return " · ".join(parts)


def _override_age(seconds: float) -> str:
    days = int(seconds // 86400)
    if days:
        return f"{days}d"
    return format_capacity_duration(seconds)


def _timestamp(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OverflowError, OSError, ValueError):
        return "?"


def _fmt(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _empty_charged_message(view: Any) -> str:
    if view.admission_blocked:
        return "No known charged claims — free capacity is unknown"
    return f"Nothing holds capacity — all {_fmt(view.limit)} units are free"


def _rstrip_text(text: Text) -> Text:
    while text.plain.endswith(("\n", " ")):
        text = text[:-1]
    return text
