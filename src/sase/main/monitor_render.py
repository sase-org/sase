"""Rendering and JSON shapes for the ``sase monitor`` command surface."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.core.time import get_timezone
from sase.monitor.models import MonitorRecord
from sase.monitor.naming import short_monitor_id

# Bumped only when the JSON payloads below change incompatibly.
MONITOR_JSON_SCHEMA_VERSION = 1

STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "running": ("●", "bold green"),
    "completed": ("✓", "bold cyan"),
    "failed": ("✗", "bold red"),
    "timeout": ("⏱", "bold red"),
    "stopped": ("⊘", "bold magenta"),
    "lost": ("?", "bold red"),
}
_UNKNOWN_DISPLAY = ("?", "dim")
_BORDER_STYLE = "#5FAFFF"
_TERMINAL_ROW_STYLE = "dim"
_EMPTY_HINT = (
    "Nothing here yet. Start one with:\n\n"
    "  sase monitor start -c '<command>' -r '<reason>' -t <timeout>\n\n"
    "Then follow it with `sase monitor show <id> --follow`."
)


def _status_display(monitor_state: str) -> tuple[str, str]:
    """Return the ``(glyph, style)`` pair for a monitor state."""
    return STATUS_DISPLAY.get(monitor_state, _UNKNOWN_DISPLAY)


def status_text(monitor_state: str) -> Text:
    """Return the colored ``<glyph> <state>`` label for a monitor state."""
    glyph, style = _status_display(monitor_state)
    return Text(f"{glyph} {monitor_state}", style=style)


#: Marks a monitor whose ``--next`` follow-up did not launch (or launched
#: degraded), so a stalled lane is visible without reading ``done.json`` or
#: passing ``--json``.
_FOLLOWUP_ERROR_GLYPH = "⚑"
_FOLLOWUP_ERROR_STYLE = "bold yellow"


def _state_cell(record: MonitorRecord) -> Text:
    """Return the STATE cell, flagged when the follow-up needs a human."""
    text = status_text(record.monitor_state)
    if record.followup_needs_attention:
        text.append(f" {_FOLLOWUP_ERROR_GLYPH}", style=_FOLLOWUP_ERROR_STYLE)
    return text


def _parse_started(timestamp: str) -> datetime | None:
    try:
        return datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=get_timezone()
        )
    except ValueError:
        return None


def _duration_seconds(record: MonitorRecord) -> float | None:
    """Return how long a monitor has run, or ``None`` when that's unknown."""
    if record.elapsed_seconds is not None:
        return record.elapsed_seconds
    if record.monitor_state != "running":
        return None
    started = _parse_started(record.timestamp)
    if started is None:
        return None
    now = datetime.now(get_timezone())
    return max(0.0, (now - started).total_seconds())


def _duration_label(record: MonitorRecord) -> str:
    from sase.ace.hooks.timestamps import format_duration

    seconds = _duration_seconds(record)
    return "—" if seconds is None else format_duration(seconds)


def _relative_start(record: MonitorRecord) -> str:
    from sase.notifications.models import format_relative_time

    started = _parse_started(record.timestamp)
    if started is None:
        return record.timestamp
    return format_relative_time(started.isoformat())


def _exit_code_text(record: MonitorRecord) -> Text:
    if record.exit_code is None:
        return Text("—", style="dim")
    style = "dim" if record.exit_code == 0 else "bold red"
    return Text(str(record.exit_code), style=style)


def _monitor_json(record: MonitorRecord) -> dict[str, Any]:
    """Return the stable JSON shape for one monitor."""
    return {
        "monitor_id": record.monitor_id,
        "short_id": short_monitor_id(record.monitor_id),
        "member_agent_name": record.member_agent_name,
        "lane": record.lane,
        "project_name": record.project_name,
        "artifacts_dir": record.artifacts_dir,
        "timestamp": record.timestamp,
        "command": record.command,
        "cwd": record.cwd,
        "reason": record.reason,
        "label": record.label,
        "start_status": record.start_status,
        "stop_status": record.stop_status,
        "timeout_seconds": record.timeout_seconds,
        "idle_timeout_seconds": record.idle_timeout_seconds,
        "tail_lines": record.tail_lines,
        "next_output": record.next_output,
        "monitor_state": record.monitor_state,
        "status_bucket": record.status_bucket,
        "is_terminal": record.is_terminal,
        "settled": record.settled,
        "next_action": record.next_action,
        "pid": record.pid,
        "exit_code": record.exit_code,
        "elapsed_seconds": _duration_seconds(record),
        "output_truncated": record.output_truncated,
        "starter_agent": record.starter_agent,
        "followup_agent": record.followup_agent,
        "request_fingerprint": record.request_fingerprint,
        "followup_outcome": record.followup_outcome,
        "followup_error": record.followup_error,
        "followup_degraded_reason": record.followup_degraded_reason,
    }


def monitor_list_json(
    records: Sequence[MonitorRecord],
    *,
    scope: dict[str, Any],
) -> dict[str, Any]:
    """Return the stable ``sase monitor list`` JSON envelope."""
    return {
        "schema_version": MONITOR_JSON_SCHEMA_VERSION,
        "count": len(records),
        "scope": scope,
        "monitors": [_monitor_json(record) for record in records],
    }


def monitor_show_json(record: MonitorRecord, *, output: str) -> dict[str, Any]:
    """Return the stable ``sase monitor show`` JSON envelope."""
    return {
        "schema_version": MONITOR_JSON_SCHEMA_VERSION,
        "monitor": _monitor_json(record),
        "output": output,
    }


def monitor_start_json(record: MonitorRecord, *, handed_off: bool) -> dict[str, Any]:
    """Return the stable ``sase monitor start`` JSON envelope."""
    return {
        "schema_version": MONITOR_JSON_SCHEMA_VERSION,
        "monitor": _monitor_json(record),
        "handed_off": handed_off,
    }


def monitor_stop_json(record: MonitorRecord, *, changed: bool) -> dict[str, Any]:
    """Return the stable ``sase monitor stop`` JSON envelope."""
    return {
        "schema_version": MONITOR_JSON_SCHEMA_VERSION,
        "changed": changed,
        "monitor": _monitor_json(record),
    }


def monitor_table(records: Sequence[MonitorRecord], *, title: str) -> Panel:
    """Render monitors as the newest-first table panel."""
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        pad_edge=False,
        show_edge=False,
    )
    table.add_column("STATE", no_wrap=True)
    table.add_column("ID", no_wrap=True)
    table.add_column("LABEL", overflow="ellipsis", no_wrap=True, ratio=1)
    table.add_column("AGENT/MEMBER", overflow="ellipsis", no_wrap=True)
    table.add_column("ELAPSED", justify="right", no_wrap=True)
    table.add_column("EXIT", justify="right", no_wrap=True)
    table.add_column("STARTED", justify="right", no_wrap=True)

    for record in records:
        terminal = record.is_terminal
        row_style = _TERMINAL_ROW_STYLE if terminal else ""
        table.add_row(
            _state_cell(record),
            Text(short_monitor_id(record.monitor_id), style=row_style or "bold"),
            Text(record.label, style=row_style),
            Text(f"{record.lane}/{record.member_agent_name}", style=row_style or "dim"),
            Text(_duration_label(record), style=row_style or "dim"),
            _exit_code_text(record),
            Text(_relative_start(record), style=row_style or "dim"),
        )

    return Panel(
        table,
        title=title,
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def empty_monitor_panel(title: str, *, hint: str | None = None) -> Panel:
    """Render the friendly empty state that names ``sase monitor start``."""
    body = Text(_EMPTY_HINT, style="dim")
    if hint:
        body.append(f"\n\n{hint}", style="#FFD700")
    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def monitor_list_markdown(records: Sequence[MonitorRecord]) -> str:
    """Render monitors as a plain markdown table."""
    if not records:
        return "_No monitors._\n"
    header = "| State | Id | Label | Agent/Member | Elapsed | Exit | Started |"
    divider = "| --- | --- | --- | --- | --- | --- | --- |"
    rows = [header, divider]
    for record in records:
        exit_code = "—" if record.exit_code is None else str(record.exit_code)
        state: str = record.monitor_state
        if record.followup_needs_attention:
            state = f"{state} {_FOLLOWUP_ERROR_GLYPH}"
        rows.append(
            "| {state} | {id} | {label} | {member} | {elapsed} | {exit} | {started} |".format(
                state=state,
                id=short_monitor_id(record.monitor_id),
                label=record.label,
                member=f"{record.lane}/{record.member_agent_name}",
                elapsed=_duration_label(record),
                exit=exit_code,
                started=_relative_start(record),
            )
        )
    return "\n".join(rows) + "\n"


def monitor_detail(record: MonitorRecord) -> Panel:
    """Render the header panel shown by ``sase monitor show``."""
    table = Table(box=None, show_header=False, pad_edge=False, expand=True)
    table.add_column("field", style="dim", no_wrap=True)
    table.add_column("value", overflow="fold", ratio=1)

    rows: list[tuple[str, RenderableType]] = [
        ("Status", status_text(record.monitor_state)),
        (
            "Id",
            Text(f"{record.monitor_id}  ({short_monitor_id(record.monitor_id)})"),
        ),
        ("Agent", Text(record.lane)),
        ("Member", Text(record.member_agent_name)),
        ("Command", Text(record.command)),
        ("Cwd", Text(record.cwd)),
        ("Reason", Text(record.reason)),
    ]
    if record.next_action:
        rows.append(("Next action", Text(record.next_action)))
    rows.extend(
        [
            ("Started", Text(_relative_start(record))),
            ("Elapsed", Text(_duration_label(record))),
            (
                "Timeout",
                Text(_duration_label_seconds(record.timeout_seconds)),
            ),
        ]
    )
    if record.idle_timeout_seconds > 0:
        rows.append(
            (
                "Idle timeout",
                Text(_duration_label_seconds(record.idle_timeout_seconds)),
            )
        )
    if record.exit_code is not None:
        rows.append(("Exit code", _exit_code_text(record)))
    if record.pid is not None:
        rows.append(("Supervisor pid", Text(str(record.pid))))
    if record.starter_agent:
        rows.append(("Starter", Text(record.starter_agent)))
    if record.followup_agent:
        rows.append(("Follow-up", Text(record.followup_agent)))
    if record.followup_error:
        rows.append(
            (
                "Follow-up error",
                Text(record.followup_error, style="bold yellow"),
            )
        )
    if record.followup_degraded_reason:
        rows.append(
            (
                "Follow-up degraded",
                Text(record.followup_degraded_reason, style="bold yellow"),
            )
        )
    if record.output_truncated:
        rows.append(
            ("Output", Text("truncated (head + tail retained)", style="yellow"))
        )

    for name, value in rows:
        table.add_row(name, value)

    return Panel(
        Group(table),
        title=record.label,
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def _duration_label_seconds(seconds: float) -> str:
    from sase.ace.hooks.timestamps import format_duration

    return format_duration(seconds)


__all__ = [
    "MONITOR_JSON_SCHEMA_VERSION",
    "STATUS_DISPLAY",
    "empty_monitor_panel",
    "monitor_detail",
    "monitor_list_json",
    "monitor_list_markdown",
    "monitor_show_json",
    "monitor_start_json",
    "monitor_stop_json",
    "monitor_table",
    "status_text",
]
