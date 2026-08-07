"""Cursor line/column readout formatting for prompt input panes.

Kept pure (no widget access beyond ``cursor_location``) so the formatting
rules are unit-testable without a running app.
"""

from __future__ import annotations

from typing import Any

from rich.cells import cell_len
from rich.text import Text

CURSOR_READOUT_MODE_COLORS: dict[str, str] = {
    "normal": "#D0A215",
    "insert": "#3AA99F",
    "visual": "#CE5D97",
    "visual_line": "#CE5D97",
}

_READOUT_LABEL_STYLE = "dim"


def cursor_readout_position(text_area: Any) -> tuple[int, int]:
    """Return *text_area*'s cursor as a 1-based ``(line, column)`` pair.

    ``cursor_location`` is already the selection's cursor end, so VISUAL mode
    needs no special handling.
    """
    row, column = text_area.cursor_location
    return row + 1, column + 1


def _readout_plain(line: int, column: int) -> str:
    return f"Ln {line}, Col {column}"


def cursor_readout_cell_width(line: int, column: int) -> int:
    """Return the rendered cell width of the ``Ln <line>, Col <column>`` readout."""
    return cell_len(_readout_plain(line, column))


def format_cursor_readout(
    line: int, column: int, *, vim_mode: str, dim: bool = False
) -> Text:
    """Return ``Ln <line>, Col <column>`` with digits colored by *vim_mode*.

    The literal words and comma stay dim/muted; the digits are painted the
    color of that pane's own vim-mode cursor, tying the readout into the
    existing cursor-color visual language. Unknown modes default to the
    INSERT color, mirroring ``LineRenderingMixin._VIM_MODE_CLASSES``.
    """
    color = CURSOR_READOUT_MODE_COLORS.get(
        vim_mode, CURSOR_READOUT_MODE_COLORS["insert"]
    )
    digit_style = f"dim {color}" if dim else color
    text = Text(no_wrap=True)
    text.append("Ln ", style=_READOUT_LABEL_STYLE)
    text.append(str(line), style=digit_style)
    text.append(", ", style=_READOUT_LABEL_STYLE)
    text.append("Col ", style=_READOUT_LABEL_STYLE)
    text.append(str(column), style=digit_style)
    return text
