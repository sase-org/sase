"""Line-number gutter for pager section bodies.

Pure and Textual-free: wrap each logical line at a content width, prefix
gutter cells, and return exact row maps so compose never has to
render-and-count. Wide characters use Rich cell math, never ``len()``.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.text import Text

_SEPARATOR = "│ "
_SEPARATOR_STYLE = "dim"
_NUMBER_STYLE = "dim"
_MIN_NUMBER_WIDTH = 2


def number_width(max_line_count: int) -> int:
    """Return the digit-column count for a document-wide gutter."""
    return max(len(str(max(max_line_count, 0))), _MIN_NUMBER_WIDTH)


def gutter_width(max_line_count: int) -> int:
    """Return gutter cells: number columns plus ``│`` and a trailing space."""
    return number_width(max_line_count) + len(_SEPARATOR)


def logical_line_count(text: str) -> int:
    """Count editor-style logical lines, dropping a phantom trailing newline.

    ``"a\\n"`` is one line; ``""`` is zero lines; a body of only ``"\\n"`` is
    one empty line.
    """
    if not text:
        return 0
    count = text.count("\n")
    if text.endswith("\n"):
        return count
    return count + 1


def _logical_lines(text: Text) -> tuple[Text, ...]:
    if not text.plain:
        return ()
    return tuple(text.split("\n"))


@dataclass(frozen=True, slots=True)
class GutterSection:
    """One section after its logical lines have been gutterized and wrapped."""

    text: Text
    row_count: int
    line_rows: tuple[int, ...]


def apply_gutter(
    text: Text,
    *,
    content_width: int,
    number_width: int,
    emphasis_line: int | None = None,
    accent: str | None = None,
) -> GutterSection:
    """Wrap *text* and prefix every visual row with gutter cells.

    ``line_rows`` maps each logical line (0-based) to its first visual row
    within the section. An empty body still occupies one visual row so
    layout never collapses, but it has no numbered lines to jump to.
    """
    wrap_width = max(content_width, 1)
    console = Console(
        width=wrap_width,
        color_system=None,
        force_terminal=False,
        highlight=False,
        markup=False,
        emoji=False,
    )
    lines = _logical_lines(text)
    visual_rows: list[Text] = []
    line_rows: list[int] = []
    for line_number, logical in enumerate(lines, start=1):
        line_rows.append(len(visual_rows))
        emphasize = emphasis_line == line_number
        wrapped = _wrap_logical_line(logical, wrap_width, console)
        for wrap_index, piece in enumerate(wrapped):
            number = line_number if wrap_index == 0 else None
            visual_rows.append(
                _guttered_row(
                    piece,
                    number=number,
                    number_width=number_width,
                    emphasize=emphasize and number is not None,
                    accent=accent,
                )
            )
    if not visual_rows:
        visual_rows.append(
            _guttered_row(
                Text(),
                number=None,
                number_width=number_width,
                emphasize=False,
                accent=None,
            )
        )
    joined = Text(no_wrap=True, overflow="crop")
    for index, row in enumerate(visual_rows):
        if index:
            joined.append("\n")
        joined.append_text(row)
    return GutterSection(
        text=joined,
        row_count=len(visual_rows),
        line_rows=tuple(line_rows),
    )


def _wrap_logical_line(text: Text, width: int, console: Console) -> tuple[Text, ...]:
    if not text.plain:
        return (Text(),)
    copied = text.copy()
    copied.overflow = "fold"
    copied.no_wrap = False
    wrapped = tuple(copied.wrap(console, width, overflow="fold"))
    return wrapped if wrapped else (Text(),)


def _guttered_row(
    piece: Text,
    *,
    number: int | None,
    number_width: int,
    emphasize: bool,
    accent: str | None,
) -> Text:
    row = Text(no_wrap=True, overflow="crop")
    row.append_text(
        _gutter_cells(
            number,
            number_width,
            emphasize=emphasize,
            accent=accent,
        )
    )
    row.append_text(piece)
    return row


def _gutter_cells(
    number: int | None,
    number_width: int,
    *,
    emphasize: bool,
    accent: str | None,
) -> Text:
    if number is None:
        label = f"{'':>{number_width}}"
        style = _NUMBER_STYLE
    else:
        label = f"{number:>{number_width}}"
        if emphasize:
            style = f"bold {accent}" if accent else "bold"
        else:
            style = _NUMBER_STYLE
    cells = Text()
    cells.append(label, style=style)
    cells.append(_SEPARATOR, style=_SEPARATOR_STYLE)
    return cells


__all__ = [
    "GutterSection",
    "apply_gutter",
    "gutter_width",
    "logical_line_count",
    "number_width",
]
