"""Shared Vim-style search command-line renderer."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._vim_search import SearchDirection


def render_search_command_line(
    *,
    direction: SearchDirection,
    query: str,
    current_index: int | None,
    total: int,
    width: int,
) -> Text:
    """Render a Vim-style ``/`` or ``?`` search status line."""
    sigil = "/" if direction == "forward" else "?"
    left = Text(no_wrap=True, overflow="crop")
    left.append(sigil, style="bold #00D7AF")
    left.append(query, style="white")
    left.append(" ", style="reverse")

    right = Text(no_wrap=True, overflow="crop")
    if query:
        if total > 0 and current_index is not None:
            right.append(f"[{current_index + 1}/{total}]", style="bold #FFD700")
        else:
            right.append("pattern not found", style="dim #FF5F5F")

    available_width = max(0, width)
    gap = "  "
    if available_width:
        padding = available_width - cell_len(left.plain) - cell_len(right.plain)
        gap = " " * max(2, padding)

    content = Text(no_wrap=True, overflow="crop")
    content.append_text(left)
    if right.plain:
        content.append(gap)
        content.append_text(right)
    return content
