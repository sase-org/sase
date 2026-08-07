"""Shared box-section rendering for the Help panel keymap reference.

Used by both the unfiltered reference and the live filter bar. With empty
runs the output is character- and style-identical to the unfiltered
reference; match runs only ever change styles, never the character stream,
so box alignment is preserved either way.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text

from ...widgets._completion_match_highlight import append_highlighted
from .binding_common import CONTENT_WIDTH
from .filter_model import FilteredRow

_KEY_WIDTH = 16
_BORDER_STYLE = "dim #87D7FF"
_HEADER_STYLE = "bold #87D7FF"
_KEY_STYLE = "bold #00D7AF"


def add_section(
    text: Text,
    name: str,
    rows: Sequence[FilteredRow],
    *,
    name_runs: tuple[tuple[int, int], ...] = (),
    content_width: int = CONTENT_WIDTH,
) -> None:
    """Append one boxed keybinding section to *text*."""
    text.append("\n")
    text.append("  \u250c\u2500 ", style=_BORDER_STYLE)
    append_highlighted(text, name, name_runs, base_style=_HEADER_STYLE)
    text.append(" ", style="")
    remaining = 50 - len(name)
    text.append("\u2500" * remaining + "\u2510", style=_BORDER_STYLE)
    text.append("\n")

    max_desc_width = content_width - _KEY_WIDTH - 2
    for row in rows:
        text.append("  \u2502  ", style=_BORDER_STYLE)
        key_display = f"{row.key:<{_KEY_WIDTH}}"
        append_highlighted(text, key_display, row.key_runs, base_style=_KEY_STYLE)

        if len(row.description) > max_desc_width:
            display_desc = row.description[: max_desc_width - 3] + "..."
        else:
            display_desc = row.description
        append_highlighted(text, display_desc, row.description_runs, base_style="")

        padding = content_width - _KEY_WIDTH - len(display_desc)
        if padding > 0:
            text.append(" " * padding, style="")
        text.append(" \u2502", style=_BORDER_STYLE)
        text.append("\n")

    text.append("  \u2514", style=_BORDER_STYLE)
    text.append("\u2500" * 53, style=_BORDER_STYLE)
    text.append("\u2518", style=_BORDER_STYLE)
    text.append("\n")


__all__ = ["add_section"]
