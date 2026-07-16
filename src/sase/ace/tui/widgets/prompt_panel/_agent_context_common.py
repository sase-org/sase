"""Shared SASE CONTEXT lane rendering helpers."""

from __future__ import annotations

from datetime import datetime

from rich.cells import cell_len
from rich.text import Text

from sase.core.time import get_timezone

# Strict total rendered-cell budget for any reason line, including the leading
# indentation, glyph prefix, and (for attributed rows) the role column. The
# available payload width is derived per row from the actual prefix width so
# wider attributed prefixes still honor the same 80-column contract.
REASON_LINE_CELL_LIMIT = 80

COLOR_MEMORY_SUBHEADER = "bold #5FD7FF"
COLOR_PLAN_SUBHEADER = "bold #AF87FF"
COLOR_SKILLS_SUBHEADER = "bold #5FD75F"
COLOR_WORKSPACE_SUBHEADER = "bold #FF87D7"
COLOR_SUMMARY = "dim"
COLOR_TIMESTAMP = "dim"
COLOR_MEMORY_GLYPH = "bold #5FD7FF"
COLOR_MEMORY_PRIMARY = "#87D7FF"
COLOR_SKILL_GLYPH = "bold #5FD75F"
COLOR_SKILL_NAME = "bold #87FF87"
COLOR_WORKSPACE_GLYPH = "bold #FF87D7"
COLOR_WORKSPACE_NAME = "bold #FFAFD7"
COLOR_WORKSPACE_PATH = "dim #D7AFD7"
COLOR_EXTERNAL_REPO_GLYPH = "bold #FFAF00"
COLOR_EXTERNAL_REPO_NAME = "bold #FFD787"
COLOR_FRONTMATTER = "dim italic"
COLOR_REASON = "#D7D7AF"
COLOR_TRUNCATION = "dim italic"
COLOR_EMPTY = "dim italic"
COLOR_ROLE = "italic #AF87FF"

MEMORY_GLYPH = "◇"
SKILL_GLYPH = "◆"
WORKSPACE_GLYPH = "▣"
EXTERNAL_REPO_GLYPH = "◆"
REASON_GLYPH = "↳"
FRONTMATTER_MARKER = "↩ frontmatter"
WORKSPACE_PATH_CONNECTOR = "→"

_ROW_LEADING = "  "
_ROW_AFTER_TIMESTAMP = "  "
_ROW_GLYPH_SEPARATOR = " "
_ROW_TIMESTAMP_DISPLAY = "HH:MM:SS"
CONTEXT_REASON_INDENT = len(
    f"{_ROW_LEADING}{_ROW_TIMESTAMP_DISPLAY}{_ROW_AFTER_TIMESTAMP}"
    f"{MEMORY_GLYPH}{_ROW_GLYPH_SEPARATOR}"
)

# Compact responsibility column rendered between timestamp and glyph for
# attributed (agent-family) rows. Labels are truncated to ROLE_LABEL_LIMIT so
# the ljust to ROLE_COLUMN_WIDTH always leaves at least one space before the
# glyph; non-attributed rows in an attributed lane render a blank column so
# the glyph/primary/reason columns stay aligned.
ROLE_LABEL_LIMIT = 6
ROLE_COLUMN_WIDTH = 7


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
    details: str | Text,
    details_style: str = COLOR_SUMMARY,
) -> None:
    text.append(f"▸ {label}", style=label_style)
    text.append(" · ", style=details_style)
    if isinstance(details, Text):
        text.append_text(details)
        text.append("\n")
    else:
        text.append(f"{details}\n", style=details_style)


def format_role_column(role_label: str | None) -> str:
    label = role_label or ""
    if len(label) > ROLE_LABEL_LIMIT:
        label = label[: ROLE_LABEL_LIMIT - 1] + "…"
    return f"{label:<{ROLE_COLUMN_WIDTH}}"


def append_lane_row(
    text: Text,
    *,
    timestamp: str,
    glyph: str,
    glyph_style: str,
    primary: str,
    primary_style: str,
    role_label: str | None = None,
    show_role_column: bool = False,
    hint_label: Text | None = None,
) -> int:
    # PLAN is a descriptive lane rather than an event log, so it deliberately
    # bypasses this shared timestamp/actor row shape. MEMORY, SKILLS, and
    # WORKSPACES keep using it so their event columns remain aligned.
    text.append(
        f"{_ROW_LEADING}{format_local_hhmmss(timestamp)}{_ROW_AFTER_TIMESTAMP}",
        style=COLOR_TIMESTAMP,
    )
    extra_indent = 0
    if show_role_column:
        column = format_role_column(role_label)
        text.append(column, style=COLOR_ROLE)
        extra_indent = len(column)
    text.append(f"{glyph}{_ROW_GLYPH_SEPARATOR}", style=glyph_style)
    hint_indent = 0
    if hint_label is not None:
        text.append_text(hint_label)
        hint_indent = cell_len(hint_label.plain)
    text.append(primary, style=primary_style)
    return CONTEXT_REASON_INDENT + extra_indent + hint_indent


def _split_token_by_cells(token: str, width: int) -> tuple[str, str]:
    """Split ``token`` into a head fitting ``width`` cells and the remainder.

    The head always contains at least one character so wrapping makes progress
    even if a single glyph is wider than ``width``.
    """
    head = ""
    head_cells = 0
    for index, char in enumerate(token):
        char_cells = cell_len(char)
        if head and head_cells + char_cells > width:
            return head, token[index:]
        head += char
        head_cells += char_cells
    return token, ""


def _wrap_reason_by_cells(reason: str, width: int) -> list[str]:
    """Wrap normalized reason text so each line fits within ``width`` cells.

    Breaks on whitespace when possible and never on hyphens. A token wider than
    ``width`` is hard-split by cells so the strict column budget always holds.
    """
    lines: list[str] = []
    current = ""
    for word in reason.split():
        while cell_len(word) > width:
            if current:
                lines.append(current)
                current = ""
            head, word = _split_token_by_cells(word, width)
            lines.append(head)
        if not current:
            current = word
        elif cell_len(current) + 1 + cell_len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def append_context_reason(
    text: Text,
    reason: str,
    *,
    indent: int,
) -> None:
    reason = normalize_context_display(reason)
    prefix = f"{' ' * indent}{REASON_GLYPH} "
    prefix_cells = cell_len(prefix)
    continuation_prefix = " " * prefix_cells
    if not reason:
        text.append(f"{prefix}\n", style=COLOR_REASON)
        return

    available = max(1, REASON_LINE_CELL_LIMIT - prefix_cells)
    lines = _wrap_reason_by_cells(reason, available)
    text.append(prefix, style=COLOR_REASON)
    text.append(lines[0] + "\n", style=COLOR_REASON)
    for line in lines[1:]:
        text.append(continuation_prefix, style=COLOR_REASON)
        text.append(line + "\n", style=COLOR_REASON)
