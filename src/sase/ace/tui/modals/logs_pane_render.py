"""Source metadata and rendering helpers for the Admin Center Logs pane."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from rich.text import Text

from sase.core.paths import sase_home
from sase.logs import TOAST_HISTORY_LIMIT, current_toast_session, read_recent_toasts

from ..logs import LogSource
from .logs_pane_toasts import render_toast_detail_body

# Palette shared with the other log-style modals (HelpModal / AgentRunLogModal).
CYAN = "#87D7FF"
GOLD = "#FFD700"

# Tail size read per source. Bounded so the panel stays responsive even on
# multi-megabyte logs (the read itself is O(tail) via ``read_tail_seek``).
_MAX_TAIL_LINES = 500

# Leading-timestamp shapes for both log formats:
#   ``[2026-06-17 14:30:00 UTC] ...``  (launch_failures.log header)
#   ``2026-06-17 14:30:00,123 WARNING ...`` (tui.log)
_TIMESTAMP_RE = re.compile(r"^\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[^\]]*\]?")
# A trailing exception-summary line, e.g. ``RuntimeError: boom``.
_EXC_SUMMARY_RE = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Interrupt|Warning):")
# Catch-all logging level tokens (uppercase, as emitted by ``logging``).
_ERROR_LEVEL_RE = re.compile(r"\b(ERROR|CRITICAL|FATAL)\b")
_WARNING_LEVEL_RE = re.compile(r"\bWARNING\b")


def format_size(num_bytes: int) -> str:
    """Human-readable byte size (``1.2 KB``, ``3 B``, ...)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_mtime(source: LogSource) -> str | None:
    """Last-modified time of *source* as ``YYYY-MM-DD HH:MM UTC``."""
    try:
        ts = source.path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _source_size(source: LogSource) -> int | None:
    try:
        return source.path.stat().st_size
    except OSError:
        return None


def _display_path(path: Path) -> str:
    """Return a stable, user-facing path for a log file."""
    try:
        resolved_path = path.expanduser().resolve(strict=False)
        resolved_home = sase_home().expanduser().resolve(strict=False)
        rel = resolved_path.relative_to(resolved_home)
    except (OSError, RuntimeError, ValueError):
        return str(path)
    return str(Path("~/.sase") / rel)


def _empty_message(source: LogSource) -> str:
    """Friendly empty-state copy for a missing/empty *source*."""
    if source.id == "launch_failures":
        return "No launch failures logged."
    if source.id == "tui_toasts":
        return "No toasts yet — notifications shown in the TUI will appear here."
    return f"No {source.title.lower()} yet."


def _line_severity_style(line: str) -> str | None:
    """Return a Rich style for a whole log *line* by severity, or ``None``."""
    stripped = line.strip()
    if stripped.startswith("Traceback (most recent call last)") or stripped == (
        "traceback:"
    ):
        return "bold red"
    if stripped.startswith("error:") or _EXC_SUMMARY_RE.match(stripped):
        return "red"
    if _ERROR_LEVEL_RE.search(line):
        return "red"
    if _WARNING_LEVEL_RE.search(line):
        return GOLD
    return None


def styled_log_line(line: str) -> Text:
    """Render one raw log *line* as colorized Rich :class:`Text`."""
    stripped = line.strip()
    # Separator rules and stack frames are de-emphasised.
    if stripped and set(stripped) <= {"=", "-", "─"}:
        return Text(line, style="dim")
    if stripped.startswith('File "'):
        return Text(line, style="dim")

    severity = _line_severity_style(line)
    if severity is not None:
        return Text(line, style=severity)

    # No severity: highlight a leading timestamp (header / tui.log) in cyan.
    match = _TIMESTAMP_RE.match(line)
    if match:
        text = Text()
        text.append(match.group(0), style=CYAN)
        text.append(line[match.end() :])
        return text
    return Text(line)


def render_log_detail(source: LogSource, max_lines: int = _MAX_TAIL_LINES) -> Text:
    """Build the full colorized detail body (header + tail) for *source*."""
    body = "" if source.render == "toasts" else source.read_rendered_tail(max_lines)
    body_text: Text | None = None
    toast_count: int | None = None
    if source.render == "toasts":
        records = read_recent_toasts(TOAST_HISTORY_LIMIT)
        toast_count = len(records)
        if records:
            body_text = render_toast_detail_body(
                records,
                current_toast_session().session_id,
            )
            body = body_text.plain
        else:
            body = ""
    text = Text()

    # Header: source title, path, last modified, and shown line count.
    text.append(source.title, style=f"bold {GOLD}")
    text.append("\n")
    text.append(f"{source.description}\n", style="dim")
    text.append(_display_path(source.path), style=f"bold {CYAN}")
    mtime = format_mtime(source)
    if mtime is not None:
        text.append(f"  ·  {mtime}", style="dim")
    if body:
        if toast_count is not None:
            text.append(f"  ·  {toast_count} toasts", style="dim")
        else:
            shown = len(body.splitlines())
            text.append(f"  ·  {shown} lines", style="dim")
    text.append("\n")
    text.append("─" * 48 + "\n", style="dim")

    if not body:
        text.append(_empty_message(source), style="dim italic")
        return text

    if body_text is not None:
        text.append_text(body_text)
        return text

    for line in body.splitlines():
        text.append_text(styled_log_line(line))
        text.append("\n")
    return text


def source_label(source: LogSource) -> Text:
    """Two-line row: ``● Title`` then a dim metadata subtitle."""
    non_empty = source.exists()
    text = Text()
    if non_empty:
        text.append("● ", style="bold green")
        text.append(source.title, style=f"bold {CYAN}")
    else:
        text.append("○ ", style="dim")
        text.append(source.title, style="dim")

    text.append("\n   ")
    if non_empty:
        size = _source_size(source)
        mtime = format_mtime(source)
        meta_parts = [p for p in (format_size(size) if size else None, mtime) if p]
        text.append(" · ".join(meta_parts) or source.description, style="dim")
    else:
        text.append("empty", style="dim italic")
    return text


__all__ = [
    "CYAN",
    "GOLD",
    "format_mtime",
    "format_size",
    "render_log_detail",
    "source_label",
    "styled_log_line",
]
