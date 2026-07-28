"""Shared visual language for indented tool-call detail blocks."""

from __future__ import annotations

from rich.text import Text

TOOL_DETAIL_GUTTER = "    │ "
TOOL_DETAIL_WRAP_INDENT = "      "


def append_tool_detail_line(
    text: Text,
    label: str,
    value: str,
    *,
    style: str = "",
) -> None:
    """Append one guttered tool-detail label/value line."""
    text.append(TOOL_DETAIL_GUTTER, style="dim")
    if label:
        text.append(f"{label} ", style="dim italic")
    text.append(value, style=style)
    text.append("\n")


def append_tool_multiline_detail(
    text: Text,
    label: str,
    value: str,
    *,
    style: str = "",
    max_lines: int = 6,
) -> None:
    """Append one guttered label followed by bounded logical value lines."""
    lines = value.replace("\r\n", "\n").replace("\r", "\n").splitlines() or [value]
    shown = lines[:max_lines]
    text.append(TOOL_DETAIL_GUTTER, style="dim")
    text.append(label, style="dim italic")
    text.append("\n")
    for line in shown:
        text.append(TOOL_DETAIL_WRAP_INDENT, style="dim")
        text.append(line, style=style)
        text.append("\n")
    remaining = len(lines) - len(shown)
    if remaining > 0:
        text.append(TOOL_DETAIL_WRAP_INDENT, style="dim")
        text.append(f"... (+{remaining} more lines)", style="dim italic")
        text.append("\n")


__all__ = [
    "TOOL_DETAIL_GUTTER",
    "TOOL_DETAIL_WRAP_INDENT",
    "append_tool_detail_line",
    "append_tool_multiline_detail",
]
