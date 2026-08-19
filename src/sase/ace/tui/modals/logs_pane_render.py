"""Source metadata and rendering helpers for the Admin Center Logs pane."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.text import Text

from sase.core.paths import sase_home
from sase.core.time import format_local, local_now, parse_local, to_local
from sase.logs import TOAST_HISTORY_LIMIT, current_toast_session, read_recent_toasts

from ..logs import LogSource
from .logs_pane_toasts import render_toast_detail_body

# Palette shared with the other log-style modals (HelpModal / AgentRunLogModal).
CYAN = "#87D7FF"
GOLD = "#FFD700"

# Tail size read per source. Bounded so the panel stays responsive even on
# multi-megabyte logs (the read itself is O(tail) via ``read_tail_seek``).
_MAX_TAIL_LINES = 500
# Wider scan used only when jumping to a registered error; still O(tail).
_MAX_FOCUS_SCAN_LINES = 5000
_FOCUS_LINE_STYLE = f"bold #1F1B00 on {GOLD}"

# Leading-timestamp shapes for both log formats:
#   ``[2026-06-17 14:30:00 UTC] ...``  (launch_failures.log header)
#   ``2026-06-17 14:30:00,123 WARNING ...`` (tui.log)
_TIMESTAMP_RE = re.compile(r"^\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[^\]]*\]?")
# A trailing exception-summary line, e.g. ``RuntimeError: boom``.
_EXC_SUMMARY_RE = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Interrupt|Warning):")
# Catch-all logging level tokens (uppercase, as emitted by ``logging``).
_ERROR_LEVEL_RE = re.compile(r"\b(ERROR|CRITICAL|FATAL)\b")
_WARNING_LEVEL_RE = re.compile(r"\bWARNING\b")


_SIZE_UNITS = ("B", "K", "M", "G", "T")


def format_size_compact(num_bytes: int) -> str:
    """Human-readable byte size in at most four cells (``17K``, ``1.7M``)."""
    size = float(max(0, num_bytes))
    index = 0
    while index + 1 < len(_SIZE_UNITS) and round(size) >= 1000:
        size /= 1024
        index += 1
    unit = _SIZE_UNITS[index]
    if index == 0:
        return f"{int(size)}{unit}"
    if size < 10:
        return f"{size:.1f}{unit}"
    return f"{round(size)}{unit}"


def format_mtime(source: LogSource) -> str | None:
    """Last-modified time of *source* in the configured timezone."""
    try:
        ts = source.path.stat().st_mtime
    except OSError:
        return None
    return format_local(ts, "%Y-%m-%d %H:%M %Z")


def _format_relative_age(epoch: float, *, now: datetime | None = None) -> str | None:
    """Compact freshness label for a log mtime (``2m ago``, ``Jun 17``)."""
    parsed = parse_local(epoch)
    if parsed is None:
        return None
    reference = now if now is not None else local_now()
    delta_seconds = max(0, int((reference - to_local(parsed)).total_seconds()))
    if delta_seconds < 60:
        return "now"
    minutes = delta_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    if days < 365:
        return format_local(epoch, "%b %d")
    return format_local(epoch, "%b %Y")


def _source_size(source: LogSource) -> int | None:
    try:
        return source.path.stat().st_size
    except OSError:
        return None


def _source_mtime_epoch(source: LogSource) -> float | None:
    try:
        return source.path.stat().st_mtime
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


def _focus_label(anchor: str) -> str:
    """Strip the bracketed error-id form used as a log-entry anchor."""
    if len(anchor) > 2 and anchor.startswith("[") and anchor.endswith("]"):
        return anchor[1:-1]
    return anchor


def _detail_header(
    source: LogSource,
    *,
    body: str,
    toast_count: int | None = None,
    extra_suffix: str | None = None,
) -> Text:
    """Build the shared detail-pane header (title, path, mtime, counts)."""
    text = Text()
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
        if extra_suffix:
            text.append(f"  ·  {extra_suffix}", style="dim")
    text.append("\n")
    text.append("─" * 48 + "\n", style="dim")
    return text


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
    text = _detail_header(source, body=body, toast_count=toast_count)

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


@dataclass(frozen=True)
class FocusedLogDetail:
    """Rendered log detail plus the 0-based line to scroll into view."""

    text: Text
    focus_line: int | None
    found: bool


def render_focused_log_detail(
    source: LogSource,
    anchor: str,
    max_lines: int = _MAX_TAIL_LINES,
    scan_lines: int = _MAX_FOCUS_SCAN_LINES,
) -> FocusedLogDetail:
    """Render a window containing *anchor*, highlighting the matching line.

    Scans a bounded tail for the last line that contains *anchor*. A recent
    hit yields the ordinary tail window; an older hit opens the window at that
    entry's separator. When the entry is gone, the ordinary tail is returned
    with an in-pane notice instead of a silent no-op.
    """
    lines = source.read_tail(scan_lines).splitlines()
    hit: int | None = None
    for index, line in enumerate(lines):
        if anchor in line:
            hit = index
    if hit is None:
        text = render_log_detail(source, max_lines)
        if text.plain and not text.plain.endswith("\n"):
            text.append("\n")
        text.append(
            f"The registered error is no longer in the last {scan_lines} lines"
            " — the log may have rotated.",
            style="dim italic",
        )
        return FocusedLogDetail(text=text, focus_line=None, found=False)

    start = hit
    if hit > 0:
        preceding = lines[hit - 1].strip()
        if preceding and set(preceding) <= {"="}:
            start = hit - 1
    start = max(0, min(start, len(lines) - max_lines))
    window = lines[start : start + max_lines]
    body = "\n".join(window)
    text = _detail_header(
        source,
        body=body,
        extra_suffix=f"focused on {_focus_label(anchor)}",
    )
    header_lines = len(text.plain.splitlines())
    focus_offset = hit - start
    for index, line in enumerate(window):
        if index == focus_offset:
            text.append(line, style=_FOCUS_LINE_STYLE)
        else:
            text.append_text(styled_log_line(line))
        text.append("\n")
    return FocusedLogDetail(
        text=text,
        focus_line=header_lines + focus_offset,
        found=True,
    )


def source_label(source: LogSource, *, now: datetime | None = None) -> Text:
    """Two-line row: ``● Title`` then a compact, non-wrapping metadata subtitle."""
    non_empty = source.exists()
    text = Text(no_wrap=True, overflow="ellipsis")
    if non_empty:
        text.append("● ", style="bold green")
        text.append(source.title, style=f"bold {CYAN}")
    else:
        text.append("○ ", style="dim")
        text.append(source.title, style="dim")

    text.append("\n  ")
    if non_empty:
        size = _source_size(source)
        mtime_epoch = _source_mtime_epoch(source)
        size_text = format_size_compact(size) if size is not None else None
        age_text = (
            _format_relative_age(mtime_epoch, now=now)
            if mtime_epoch is not None
            else None
        )
        if size_text is not None and age_text is not None:
            subtitle = f"{size_text:<4} · {age_text}"
        else:
            meta_parts = [part for part in (size_text, age_text) if part]
            subtitle = " · ".join(meta_parts) or source.description
        text.append(subtitle, style="dim")
    else:
        text.append("empty", style="dim italic")
    return text


__all__ = [
    "CYAN",
    "GOLD",
    "FocusedLogDetail",
    "format_mtime",
    "format_size_compact",
    "render_focused_log_detail",
    "render_log_detail",
    "source_label",
    "styled_log_line",
]
