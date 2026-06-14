"""Shared AGENT CONTEXT lane rendering helpers."""

from __future__ import annotations

import textwrap
from datetime import datetime

from rich.text import Text

from sase.core.time import get_timezone

REASON_WRAP_WIDTH = 88

COLOR_MEMORY_SUBHEADER = "bold #5FD7FF"
COLOR_SKILLS_SUBHEADER = "bold #5FD75F"
COLOR_SUMMARY = "dim"
COLOR_TIMESTAMP = "dim"
COLOR_MEMORY_GLYPH = "bold #5FD7FF"
COLOR_MEMORY_PRIMARY = "#87D7FF"
COLOR_SKILL_GLYPH = "bold #5FD75F"
COLOR_SKILL_NAME = "bold #87FF87"
COLOR_FRONTMATTER = "dim italic"
COLOR_REASON = "#D7D7AF"
COLOR_TRUNCATION = "dim italic"
COLOR_EMPTY = "dim italic"

MEMORY_GLYPH = "◇"
SKILL_GLYPH = "◆"
REASON_GLYPH = "↳"
FRONTMATTER_MARKER = "↩ frontmatter"

_ROW_LEADING = "  "
_ROW_AFTER_TIMESTAMP = "  "
_ROW_GLYPH_SEPARATOR = " "
_ROW_TIMESTAMP_DISPLAY = "HH:MM:SS"
CONTEXT_REASON_INDENT = len(
    f"{_ROW_LEADING}{_ROW_TIMESTAMP_DISPLAY}{_ROW_AFTER_TIMESTAMP}"
    f"{MEMORY_GLYPH}{_ROW_GLYPH_SEPARATOR}"
)


def format_local_hhmmss(iso_timestamp: str) -> str:
    try:
        cleaned = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone(get_timezone()).strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return "??:??:??"


def format_local_hhmm(iso_timestamp: str) -> str:
    try:
        cleaned = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.astimezone(get_timezone()).strftime("%H:%M")
    except (ValueError, AttributeError):
        return "??:??"


def normalize_context_display(value: str) -> str:
    return " ".join(value.split())


def truncate_display(value: str, limit: int) -> str:
    value = normalize_context_display(value)
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def count_phrase(n: int, singular: str) -> str:
    suffix = "" if n == 1 else "s"
    return f"{n} {singular}{suffix}"


def append_context_lane_header(
    text: Text,
    label: str,
    *,
    label_style: str,
    details: str,
    details_style: str = COLOR_SUMMARY,
) -> None:
    text.append(f"▸ {label}", style=label_style)
    text.append(f" · {details}\n", style=details_style)


def append_lane_row(
    text: Text,
    *,
    timestamp: str,
    glyph: str,
    glyph_style: str,
    primary: str,
    primary_style: str,
) -> int:
    text.append(
        f"{_ROW_LEADING}{format_local_hhmmss(timestamp)}{_ROW_AFTER_TIMESTAMP}",
        style=COLOR_TIMESTAMP,
    )
    text.append(f"{glyph}{_ROW_GLYPH_SEPARATOR}", style=glyph_style)
    text.append(primary, style=primary_style)
    return CONTEXT_REASON_INDENT


def append_context_reason(
    text: Text,
    reason: str,
    *,
    indent: int,
) -> None:
    reason = normalize_context_display(reason)
    prefix = f"{' ' * indent}{REASON_GLYPH} "
    continuation_prefix = " " * len(prefix)
    if not reason:
        text.append(f"{prefix}\n", style=COLOR_REASON)
        return

    lines = textwrap.wrap(
        reason,
        width=REASON_WRAP_WIDTH,
        break_long_words=True,
        break_on_hyphens=False,
    )
    text.append(prefix, style=COLOR_REASON)
    text.append(lines[0] + "\n", style=COLOR_REASON)
    for line in lines[1:]:
        text.append(continuation_prefix, style=COLOR_REASON)
        text.append(line + "\n", style=COLOR_REASON)
