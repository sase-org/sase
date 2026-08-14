"""Rendering and JSON shapes for the ``sase proc`` command surface."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from typing import Any

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.core.time import format_local
from sase.sessions import session_chip, short_session_handle
from sase.procs import (
    COMMAND_PROC_KIND,
    DETACHED_PROC_KIND,
    TERMINAL_PROC_STATUSES,
    TUI_PROC_KIND,
    Proc,
    short_proc_id,
)

# Bumped only when the JSON payloads below change incompatibly.
PROC_JSON_SCHEMA_VERSION = 1

# The Procs-tab glyphs, plus a distinct pair for the two states the tab has
# no icon for: a proc that has not started yet, and one that was killed.
STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "pending": ("◌", "#FFD700"),
    "running": ("●", "bold green"),
    "success": ("✓", "bold cyan"),
    "error": ("✗", "bold red"),
    "killed": ("⊘", "bold magenta"),
}
_UNKNOWN_DISPLAY = ("?", "dim")
_KIND_DISPLAY: dict[str, tuple[str, str]] = {
    COMMAND_PROC_KIND: ("⌘", "dim"),
    TUI_PROC_KIND: ("▣", "dim"),
    DETACHED_PROC_KIND: ("◆", "bold cyan"),
}
_UNKNOWN_KIND_DISPLAY = ("?", "dim")

_BORDER_STYLE = "#5FAFFF"
_TERMINAL_ROW_STYLE = "dim"
_EMPTY_HINT = (
    "Nothing here yet. Start one with:\n\n"
    "  sase proc run -- <command>\n\n"
    "Or start globally visible work with:\n\n"
    "  sase proc run --detached -- <command>\n\n"
    "Then follow it with `sase proc show <id> --follow`."
)


def _status_display(status: str) -> tuple[str, str]:
    """Return the ``(glyph, style)`` pair for a proc status."""
    return STATUS_DISPLAY.get(status, _UNKNOWN_DISPLAY)


def status_text(status: str) -> Text:
    """Return the colored ``<glyph> <status>`` label for a proc status."""
    glyph, style = _status_display(status)
    return Text(f"{glyph} {status}", style=style)


def _kind_text(kind: str, *, verbose: bool = False) -> Text:
    """Render a consistent compact kind marker, optionally with its name."""
    glyph, style = _KIND_DISPLAY.get(kind, _UNKNOWN_KIND_DISPLAY)
    label = kind
    if kind == DETACHED_PROC_KIND and verbose:
        label = "detached (global; no session owns this proc)"
    return Text(f"{glyph} {label}" if verbose else glyph, style=style)


def _proc_duration_seconds(proc: Proc) -> float | None:
    """Return how long a proc has run, or ``None`` when it never started."""
    started = _parse_timestamp(proc.started_at)
    if started is None:
        return None
    finished = _parse_timestamp(proc.finished_at) or datetime.now(UTC)
    return max(0.0, (finished - started).total_seconds())


def _proc_json(
    proc: Proc,
    *,
    live_session_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return the stable JSON shape for one proc."""
    payload: dict[str, Any] = dict(proc.to_dict())
    payload["short_id"] = short_proc_id(proc.proc_id)
    payload["is_terminal"] = proc.status in TERMINAL_PROC_STATUSES
    payload["detached"] = proc.kind == DETACHED_PROC_KIND
    payload["duration_seconds"] = _proc_duration_seconds(proc)
    payload["session_handle"] = (
        short_session_handle(proc.session_id) if proc.session_id else None
    )
    payload["session_live"] = (
        None
        if proc.session_id is None or live_session_ids is None
        else proc.session_id in live_session_ids
    )
    return payload


def proc_list_json(
    procs: Sequence[Proc],
    *,
    scope: dict[str, Any],
    live_session_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return the stable ``sase proc list`` JSON envelope."""
    return {
        "schema_version": PROC_JSON_SCHEMA_VERSION,
        "count": len(procs),
        "scope": scope,
        "procs": [
            _proc_json(proc, live_session_ids=live_session_ids) for proc in procs
        ],
    }


def proc_show_json(
    proc: Proc,
    *,
    log: str,
    live_session_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return the stable ``sase proc show`` JSON envelope."""
    return {
        "schema_version": PROC_JSON_SCHEMA_VERSION,
        "proc": _proc_json(proc, live_session_ids=live_session_ids),
        "log": log,
    }


def proc_kill_json(
    proc: Proc,
    *,
    changed: bool,
    live_session_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return the stable ``sase proc kill`` JSON envelope."""
    return {
        "schema_version": PROC_JSON_SCHEMA_VERSION,
        "changed": changed,
        "proc": _proc_json(proc, live_session_ids=live_session_ids),
    }


def proc_table(
    procs: Sequence[Proc],
    *,
    title: str,
    live_session_ids: Collection[str] | None = None,
) -> Panel:
    """Render procs as the newest-first table panel."""
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        pad_edge=False,
        show_edge=False,
    )
    table.add_column("", no_wrap=True)
    table.add_column("ID", no_wrap=True)
    table.add_column("LABEL", overflow="ellipsis", no_wrap=True, ratio=1)
    table.add_column("SESSION", no_wrap=True)
    table.add_column("PROJECT", no_wrap=True)
    table.add_column("STARTED", justify="right", no_wrap=True)
    table.add_column("TOOK", justify="right", no_wrap=True)
    table.add_column("EXIT", justify="right", no_wrap=True)

    for proc in procs:
        terminal = proc.status in TERMINAL_PROC_STATUSES
        row_style = _TERMINAL_ROW_STYLE if terminal else ""
        glyph, glyph_style = _status_display(proc.status)
        status_and_kind = Text()
        status_and_kind.append(glyph, style=glyph_style)
        status_and_kind.append(" ")
        status_and_kind.append_text(_kind_text(proc.kind))
        table.add_row(
            status_and_kind,
            Text(short_proc_id(proc.proc_id), style=row_style or "bold"),
            Text(proc.label, style=row_style),
            session_chip(proc.to_dict(), live_session_ids=live_session_ids),
            Text(proc.project or "—", style=row_style or "dim"),
            Text(_relative_start(proc), style=row_style or "dim"),
            Text(_duration_label(proc), style=row_style or "dim"),
            _exit_code_text(proc),
        )

    return Panel(
        table,
        title=title,
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def empty_proc_panel(title: str, *, hint: str | None = None) -> Panel:
    """Render the friendly empty state that names ``sase proc run``."""
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


def proc_detail(
    proc: Proc,
    *,
    live_session_ids: Collection[str] | None = None,
) -> Panel:
    """Render the header panel shown by ``sase proc show``."""
    table = Table(box=None, show_header=False, pad_edge=False, expand=True)
    table.add_column("field", style="dim", no_wrap=True)
    table.add_column("value", overflow="fold", ratio=1)

    rows: list[tuple[str, RenderableType]] = [
        ("Status", status_text(proc.status)),
        ("Id", Text(f"{proc.proc_id}  ({short_proc_id(proc.proc_id)})")),
        ("Kind", _kind_text(proc.kind, verbose=True)),
        ("Origin", Text(proc.origin)),
        ("Session", session_chip(proc.to_dict(), live_session_ids=live_session_ids)),
        ("Project", Text(proc.project or "—")),
        ("Cwd", Text(proc.cwd)),
        ("Command", Text(_command_display(proc))),
    ]
    if proc.cl_name:
        rows.append(("Patch", Text(proc.cl_name)))
    if proc.tags:
        rows.append(("Tags", Text(", ".join(proc.tags))))
    if proc.phase:
        rows.append(("Phase", Text(proc.phase)))
    rows.extend(
        [
            ("Created", Text(format_local(proc.created_at))),
            ("Started", Text(format_local(proc.started_at))),
            ("Finished", Text(format_local(proc.finished_at))),
            ("Duration", Text(_duration_label(proc))),
        ]
    )
    if proc.exit_code is not None:
        rows.append(("Exit code", _exit_code_text(proc)))
    if proc.pid is not None:
        rows.append(("Supervisor pid", Text(str(proc.pid))))
    if proc.message:
        rows.append(("Message", Text(proc.message)))
    rows.append(("Log", Text(proc.log_path, style="dim")))

    for name, value in rows:
        table.add_row(name, value)

    return Panel(
        Group(table),
        title=proc.label,
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def _command_display(proc: Proc) -> str:
    if not proc.command:
        return "—"
    return " ".join(proc.command)


def _relative_start(proc: Proc) -> str:
    from sase.notifications.models import format_relative_time

    return format_relative_time(proc.started_at or proc.created_at)


def _duration_label(proc: Proc) -> str:
    from sase.ace.hooks.timestamps import format_duration

    seconds = _proc_duration_seconds(proc)
    return "—" if seconds is None else format_duration(seconds)


def _exit_code_text(proc: Proc) -> Text:
    if proc.exit_code is None:
        return Text("—", style="dim")
    style = "dim" if proc.exit_code == 0 else "bold red"
    return Text(str(proc.exit_code), style=style)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


TASK_JSON_SCHEMA_VERSION = PROC_JSON_SCHEMA_VERSION
empty_task_panel = empty_proc_panel
task_detail = proc_detail
task_kill_json = proc_kill_json
task_list_json = proc_list_json
task_show_json = proc_show_json
task_table = proc_table

__all__ = [
    "PROC_JSON_SCHEMA_VERSION",
    "STATUS_DISPLAY",
    "TASK_JSON_SCHEMA_VERSION",
    "empty_proc_panel",
    "empty_task_panel",
    "proc_detail",
    "proc_kill_json",
    "proc_list_json",
    "proc_show_json",
    "proc_table",
    "status_text",
    "task_detail",
    "task_kill_json",
    "task_list_json",
    "task_show_json",
    "task_table",
]
