"""Rendering and JSON shapes for the ``sase task`` command surface."""

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
from sase.tasks import (
    COMMAND_TASK_KIND,
    DETACHED_TASK_KIND,
    TERMINAL_TASK_STATUSES,
    TUI_TASK_KIND,
    BackgroundTask,
    short_task_id,
)

# Bumped only when the JSON payloads below change incompatibly.
TASK_JSON_SCHEMA_VERSION = 1

# The Tasks-tab glyphs, plus a distinct pair for the two states the tab has
# no icon for: a task that has not started yet, and one that was killed.
STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "pending": ("◌", "#FFD700"),
    "running": ("●", "bold green"),
    "success": ("✓", "bold cyan"),
    "error": ("✗", "bold red"),
    "killed": ("⊘", "bold magenta"),
}
_UNKNOWN_DISPLAY = ("?", "dim")
_KIND_DISPLAY: dict[str, tuple[str, str]] = {
    COMMAND_TASK_KIND: ("⌘", "dim"),
    TUI_TASK_KIND: ("▣", "dim"),
    DETACHED_TASK_KIND: ("◆", "bold cyan"),
}
_UNKNOWN_KIND_DISPLAY = ("?", "dim")

_BORDER_STYLE = "#5FAFFF"
_TERMINAL_ROW_STYLE = "dim"
_EMPTY_HINT = (
    "Nothing here yet. Start one with:\n\n"
    "  sase task run -- <command>\n\n"
    "Or start globally visible work with:\n\n"
    "  sase task run --detached -- <command>\n\n"
    "Then follow it with `sase task show <id> --follow`."
)


def _status_display(status: str) -> tuple[str, str]:
    """Return the ``(glyph, style)`` pair for a task status."""
    return STATUS_DISPLAY.get(status, _UNKNOWN_DISPLAY)


def status_text(status: str) -> Text:
    """Return the colored ``<glyph> <status>`` label for a task status."""
    glyph, style = _status_display(status)
    return Text(f"{glyph} {status}", style=style)


def _kind_text(kind: str, *, verbose: bool = False) -> Text:
    """Render a consistent compact kind marker, optionally with its name."""
    glyph, style = _KIND_DISPLAY.get(kind, _UNKNOWN_KIND_DISPLAY)
    label = kind
    if kind == DETACHED_TASK_KIND and verbose:
        label = "detached (global; no session owns this task)"
    return Text(f"{glyph} {label}" if verbose else glyph, style=style)


def _task_duration_seconds(task: BackgroundTask) -> float | None:
    """Return how long a task has run, or ``None`` when it never started."""
    started = _parse_timestamp(task.started_at)
    if started is None:
        return None
    finished = _parse_timestamp(task.finished_at) or datetime.now(UTC)
    return max(0.0, (finished - started).total_seconds())


def _task_json(
    task: BackgroundTask,
    *,
    live_session_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return the stable JSON shape for one task."""
    payload: dict[str, Any] = dict(task.to_dict())
    payload["short_id"] = short_task_id(task.task_id)
    payload["is_terminal"] = task.status in TERMINAL_TASK_STATUSES
    payload["detached"] = task.kind == DETACHED_TASK_KIND
    payload["duration_seconds"] = _task_duration_seconds(task)
    payload["session_handle"] = (
        short_session_handle(task.session_id) if task.session_id else None
    )
    payload["session_live"] = (
        None
        if task.session_id is None or live_session_ids is None
        else task.session_id in live_session_ids
    )
    return payload


def task_list_json(
    tasks: Sequence[BackgroundTask],
    *,
    scope: dict[str, Any],
    live_session_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return the stable ``sase task list`` JSON envelope."""
    return {
        "schema_version": TASK_JSON_SCHEMA_VERSION,
        "count": len(tasks),
        "scope": scope,
        "tasks": [
            _task_json(task, live_session_ids=live_session_ids) for task in tasks
        ],
    }


def task_show_json(
    task: BackgroundTask,
    *,
    log: str,
    live_session_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return the stable ``sase task show`` JSON envelope."""
    return {
        "schema_version": TASK_JSON_SCHEMA_VERSION,
        "task": _task_json(task, live_session_ids=live_session_ids),
        "log": log,
    }


def task_kill_json(
    task: BackgroundTask,
    *,
    changed: bool,
    live_session_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return the stable ``sase task kill`` JSON envelope."""
    return {
        "schema_version": TASK_JSON_SCHEMA_VERSION,
        "changed": changed,
        "task": _task_json(task, live_session_ids=live_session_ids),
    }


def task_table(
    tasks: Sequence[BackgroundTask],
    *,
    title: str,
    live_session_ids: Collection[str] | None = None,
) -> Panel:
    """Render tasks as the newest-first table panel."""
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

    for task in tasks:
        terminal = task.status in TERMINAL_TASK_STATUSES
        row_style = _TERMINAL_ROW_STYLE if terminal else ""
        glyph, glyph_style = _status_display(task.status)
        status_and_kind = Text()
        status_and_kind.append(glyph, style=glyph_style)
        status_and_kind.append(" ")
        status_and_kind.append_text(_kind_text(task.kind))
        table.add_row(
            status_and_kind,
            Text(short_task_id(task.task_id), style=row_style or "bold"),
            Text(task.label, style=row_style),
            session_chip(task.to_dict(), live_session_ids=live_session_ids),
            Text(task.project or "—", style=row_style or "dim"),
            Text(_relative_start(task), style=row_style or "dim"),
            Text(_duration_label(task), style=row_style or "dim"),
            _exit_code_text(task),
        )

    return Panel(
        table,
        title=title,
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def empty_task_panel(title: str, *, hint: str | None = None) -> Panel:
    """Render the friendly empty state that names ``sase task run``."""
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


def task_detail(
    task: BackgroundTask,
    *,
    live_session_ids: Collection[str] | None = None,
) -> Panel:
    """Render the header panel shown by ``sase task show``."""
    table = Table(box=None, show_header=False, pad_edge=False, expand=True)
    table.add_column("field", style="dim", no_wrap=True)
    table.add_column("value", overflow="fold", ratio=1)

    rows: list[tuple[str, RenderableType]] = [
        ("Status", status_text(task.status)),
        ("Id", Text(f"{task.task_id}  ({short_task_id(task.task_id)})")),
        ("Kind", _kind_text(task.kind, verbose=True)),
        ("Origin", Text(task.origin)),
        ("Session", session_chip(task.to_dict(), live_session_ids=live_session_ids)),
        ("Project", Text(task.project or "—")),
        ("Cwd", Text(task.cwd)),
        ("Command", Text(_command_display(task))),
    ]
    if task.cl_name:
        rows.append(("ChangeSpec", Text(task.cl_name)))
    if task.tags:
        rows.append(("Tags", Text(", ".join(task.tags))))
    if task.phase:
        rows.append(("Phase", Text(task.phase)))
    rows.extend(
        [
            ("Created", Text(format_local(task.created_at))),
            ("Started", Text(format_local(task.started_at))),
            ("Finished", Text(format_local(task.finished_at))),
            ("Duration", Text(_duration_label(task))),
        ]
    )
    if task.exit_code is not None:
        rows.append(("Exit code", _exit_code_text(task)))
    if task.pid is not None:
        rows.append(("Supervisor pid", Text(str(task.pid))))
    if task.message:
        rows.append(("Message", Text(task.message)))
    rows.append(("Log", Text(task.log_path, style="dim")))

    for name, value in rows:
        table.add_row(name, value)

    return Panel(
        Group(table),
        title=task.label,
        title_align="left",
        border_style=_BORDER_STYLE,
        box=box.ROUNDED,
    )


def _command_display(task: BackgroundTask) -> str:
    if not task.command:
        return "—"
    return " ".join(task.command)


def _relative_start(task: BackgroundTask) -> str:
    from sase.notifications.models import format_relative_time

    return format_relative_time(task.started_at or task.created_at)


def _duration_label(task: BackgroundTask) -> str:
    from sase.ace.hooks.timestamps import format_duration

    seconds = _task_duration_seconds(task)
    return "—" if seconds is None else format_duration(seconds)


def _exit_code_text(task: BackgroundTask) -> Text:
    if task.exit_code is None:
        return Text("—", style="dim")
    style = "dim" if task.exit_code == 0 else "bold red"
    return Text(str(task.exit_code), style=style)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


__all__ = [
    "STATUS_DISPLAY",
    "TASK_JSON_SCHEMA_VERSION",
    "empty_task_panel",
    "status_text",
    "task_detail",
    "task_kill_json",
    "task_list_json",
    "task_show_json",
    "task_table",
]
