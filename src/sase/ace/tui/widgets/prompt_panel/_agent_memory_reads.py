"""Agent-specific MEMORY READS section helpers for the prompt panel header."""

from __future__ import annotations

import textwrap
from datetime import datetime

from rich.text import Text

from sase.core.time import get_timezone
from sase.memory.read_log import MemoryReadEvent

MAX_VISIBLE_READS = 5
REASON_WRAP_WIDTH = 88
PATH_LIMIT = 64

_COLOR_HEADER = "bold #D7AF5F underline"
_COLOR_SUMMARY = "dim"
_COLOR_TIMESTAMP = "dim"
_COLOR_PATH = "#87D7FF"
_COLOR_FRONTMATTER = "dim italic"
_COLOR_REASON = "#D7D7AF"
_COLOR_TRUNCATION = "dim italic"
_FRONTMATTER_MARKER = "  ↩ frontmatter"
_REASON_GLYPH = "↳"
_REASON_PREFIX = f"            {_REASON_GLYPH} "
_REASON_CONTINUATION_PREFIX = " " * len(_REASON_PREFIX)


def _format_local_hhmmss(iso_timestamp: str) -> str:
    try:
        cleaned = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone(get_timezone()).strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return "??:??:??"


def _format_local_hhmm(iso_timestamp: str) -> str:
    try:
        cleaned = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone(get_timezone()).strftime("%H:%M")
    except (ValueError, AttributeError):
        return "??:??"


def _normalize_display(value: str) -> str:
    return " ".join(value.split())


def _truncate_path(value: str, limit: int) -> str:
    value = _normalize_display(value)
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def _append_reason(text: Text, reason: str) -> None:
    reason = _normalize_display(reason)
    if not reason:
        text.append(f"{_REASON_PREFIX}\n", style=_COLOR_REASON)
        return

    lines = textwrap.wrap(
        reason,
        width=REASON_WRAP_WIDTH,
        break_long_words=True,
        break_on_hyphens=False,
    )
    text.append(_REASON_PREFIX, style=_COLOR_REASON)
    text.append(lines[0] + "\n", style=_COLOR_REASON)
    for line in lines[1:]:
        text.append(_REASON_CONTINUATION_PREFIX, style=_COLOR_REASON)
        text.append(line + "\n", style=_COLOR_REASON)


def append_agent_memory_reads_section(
    text: Text,
    *,
    events: tuple[MemoryReadEvent, ...] = (),
) -> None:
    """Append a MEMORY READS section listing the agent's audited reads."""
    if not events:
        return

    distinct_paths = len({event.canonical_path for event in events})
    latest = events[0]

    text.append("MEMORY READS\n", style=_COLOR_HEADER)
    text.append(
        f"{len(events)} reads · {distinct_paths} files "
        f"· last {_format_local_hhmmss(latest.timestamp)}\n\n",
        style=_COLOR_SUMMARY,
    )

    visible = events[:MAX_VISIBLE_READS]
    for event in visible:
        text.append(
            f"  {_format_local_hhmmss(event.timestamp)}  ", style=_COLOR_TIMESTAMP
        )
        text.append(_truncate_path(event.canonical_path, PATH_LIMIT), style=_COLOR_PATH)
        if event.frontmatter_stripped:
            text.append(_FRONTMATTER_MARKER, style=_COLOR_FRONTMATTER)
        text.append("\n")
        _append_reason(text, event.reason)

    overflow = len(events) - len(visible)
    if overflow > 0:
        earliest = events[-1]
        text.append(
            f"  + {overflow} more  ({_format_local_hhmm(earliest.timestamp)} earliest)\n",
            style=_COLOR_TRUNCATION,
        )
