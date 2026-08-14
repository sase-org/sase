"""Pure rendering helpers for the Admin Center Tasks tab.

Nothing here reads a file, stats the store, or touches a lock: the Tasks
pane renders on the event loop, so every function below works only from the
row it is handed.
"""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.sessions import session_chip
from sase.core.time import local_now
from sase.procs import DETACHED_PROC_KIND

from ..proc_queue import ProcInfo, ProcLogLine
from ..proc_subprocess import command_display

_STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "pending": ("◌", "dim"),
    "running": ("●", "bold green"),
    "success": ("✓", "bold cyan"),
    "error": ("✗", "bold red"),
    "killed": ("⊘", "bold yellow"),
}
_SPINNER_FRAMES = ("|", "/", "-", "\\")
_ACTIVE_STATUSES = frozenset({"pending", "running"})
_MAX_RENDERED_LOG_LINES = 1_200

_RULE = "─" * 60
_DETACHED_MARKER = "◆ detached"

# Rendered body cache: task id -> (log version, static text, rendered body).
BodyCache = dict[str, tuple[int, str | None, Text]]


def is_active(task: ProcInfo) -> bool:
    """Return whether a row is still pending or running."""
    return task.status in _ACTIVE_STATUSES


def _relative_time(dt: datetime, *, now: datetime | None = None) -> str:
    """Format a datetime as a short relative time string."""
    reference = now if now is not None else local_now()
    delta = int((reference - dt).total_seconds())
    if delta < 0:
        return "just now"
    if delta < 60:
        return f"{delta}s ago"
    minutes = delta // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _elapsed(task: ProcInfo, *, now: datetime | None = None) -> str:
    """Format how long a task has been running, or ran for."""
    end = task.finished_at or now or local_now()
    seconds = max(0, int((end - task.started_at).total_seconds()))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def _task_status_token(task: ProcInfo, *, spinner_index: int) -> tuple[str, str]:
    """Return the glyph and style for a task's status."""
    if task.status == "running":
        return _SPINNER_FRAMES[spinner_index % len(_SPINNER_FRAMES)], "bold green"
    return _STATUS_DISPLAY.get(task.status, ("?", "dim"))


def _row_session_chip(task: ProcInfo) -> Text | None:
    """Return the session badge for a store-backed row, if it needs one.

    In-memory rows always belong to this session and stay chip-free. Detached
    rows use their explicit marker instead; every other store-backed row gets
    a chip so foreign or unattributed ownership is visible at a glance.
    """
    if not task.store_backed or task.proc_type == DETACHED_PROC_KIND:
        return None
    live_ids: frozenset[str] = frozenset()
    if task.session_live and task.session_id is not None:
        live_ids = frozenset({task.session_id})
    return session_chip(
        {"session_id": task.session_id, "session_label": task.session_label},
        live_session_ids=live_ids,
    )


def _append_detached_marker(
    text: Text,
    task: ProcInfo,
    *,
    prefix: str = "  ",
    suffix: str = "",
) -> None:
    """Mark a globally owned task without introducing another color family."""
    if task.proc_type == DETACHED_PROC_KIND:
        text.append(f"{prefix}{_DETACHED_MARKER}{suffix}", style="bold cyan")


def task_row_label(task: ProcInfo) -> Text:
    """Build the styled option-list entry for one task."""
    icon, icon_style = _STATUS_DISPLAY.get(task.status, ("?", "dim"))
    text = Text()
    text.append(f"{icon} ", style=icon_style)
    _append_detached_marker(text, task, prefix="", suffix=" ")
    text.append(task.label, style="bold")
    time_ref = task.finished_at or task.started_at
    text.append(f"  {_relative_time(time_ref)}", style="dim")
    chip = _row_session_chip(task)
    if chip is not None:
        text.append("  ")
        text.append_text(chip)
    secondary = task.phase or ("Working..." if is_active(task) else task.message)
    if secondary:
        text.append(f"\n   {secondary}", style="dim")
    return text


def output_header(task: ProcInfo, *, spinner_index: int) -> Text:
    """Build the output-pane header for one task."""
    out = Text()
    icon, style = _task_status_token(task, spinner_index=spinner_index)
    out.append(task.label, style="bold")
    _append_detached_marker(out, task)
    out.append("  ")
    out.append(icon, style=style)
    out.append(f"  {_elapsed(task)}", style="dim")
    chip = _row_session_chip(task)
    if chip is not None:
        out.append("  ")
        out.append_text(chip)
    if task.command:
        out.append("\n$ ", style="dim")
        out.append(command_display(task.command), style="dim")
    phase = task.phase
    if is_active(task):
        phase = phase or "Working..."
    elif phase is None and task.message:
        phase = task.message
    if phase:
        out.append("\n")
        out.append(phase, style="bold green" if is_active(task) else "dim")
    out.append("\n")
    out.append(_RULE, style="dim")
    return out


def output_footer(task: ProcInfo) -> Text:
    """Build the terminal-state summary shown under a finished task."""
    out = Text()
    out.append(_RULE, style="dim")
    out.append("\n")
    if task.status == "success":
        out.append("✓ ", style="bold cyan")
        out.append(task.message or "Completed", style="bold cyan")
    elif task.status == "killed":
        out.append("⊘ ", style="bold yellow")
        out.append(task.message or "Killed", style="bold yellow")
    elif task.status == "error":
        out.append("✗ ", style="bold red")
        out.append(task.error or task.message or "Failed", style="bold red")
    else:
        out.append(task.message, style="dim")
    out.append(f"  ({_elapsed(task)})", style="dim")
    return out


def output_body(task: ProcInfo, cache: BodyCache) -> Text:
    """Render a task's output body, memoized per task in *cache*.

    Store-backed rows carry their log tail in ``output`` and keep an empty
    in-memory log, so the cache key pairs the log version with whatever
    static text is being shown.
    """
    snapshot = task.log.snapshot()
    legacy = None
    final_output = None
    if not snapshot.lines and task.output:
        final_output = task.output
    elif not snapshot.lines and task._live_buffer is not None:  # noqa: SLF001
        legacy = task._live_buffer.getvalue()  # noqa: SLF001
    static_text = legacy or final_output
    cached = cache.get(task.proc_id)
    if (
        cached is not None
        and cached[0] == snapshot.version
        and cached[1] == static_text
    ):
        return cached[2].copy()

    out = Text()
    if static_text:
        out.append_text(Text.from_ansi(static_text))
    else:
        out.append_text(_log_body(snapshot.lines, snapshot.trimmed_count))
    cache[task.proc_id] = (snapshot.version, static_text, out.copy())
    return out


def cached_body_version(task: ProcInfo, cache: BodyCache) -> int:
    """Return the log version the cached body was rendered from."""
    cached = cache.get(task.proc_id)
    return -1 if cached is None else cached[0]


def _log_body(lines: tuple[ProcLogLine, ...], trimmed_count: int) -> Text:
    """Render retained log lines, noting anything trimmed or hidden."""
    out = Text()
    if trimmed_count:
        out.append(f"... {trimmed_count} earlier lines trimmed\n", style="dim italic")
    if len(lines) > _MAX_RENDERED_LOG_LINES:
        hidden = len(lines) - _MAX_RENDERED_LOG_LINES
        out.append(f"... {hidden} earlier retained lines hidden\n", style="dim")
        lines = lines[-_MAX_RENDERED_LOG_LINES:]
    for line in lines:
        out.append_text(_render_log_line(line))
        out.append("\n")
    return out


def _render_log_line(line: ProcLogLine) -> Text:
    """Style one retained log line by stream and content."""
    if line.stream == "progress":
        return Text(line.text, style="bold #48CAE4")
    if line.stream == "header":
        return Text(line.text, style="dim")
    if line.stream == "result":
        style = "bold red" if line.text.startswith("ERROR") else "bold cyan"
        return Text(line.text, style=style)

    rendered = Text.from_ansi(line.text)
    lower = line.text.lower()
    if line.stream == "stderr":
        rendered.stylize("red")
    elif "error" in lower or "failed" in lower:
        rendered.stylize("bold red")
    elif "warning" in lower or "conflict" in lower:
        rendered.stylize("yellow")
    return rendered


__all__ = [
    "BodyCache",
    "cached_body_version",
    "is_active",
    "output_body",
    "output_footer",
    "output_header",
    "task_row_label",
]
