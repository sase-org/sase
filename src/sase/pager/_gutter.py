"""Line-number gutter for pager section bodies.

Pure and Textual-free: wrap each logical line at a content width, prefix
gutter cells, and return exact row maps so compose never has to
render-and-count. Wide characters use Rich cell math, never ``len()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.text import Text

_SEPARATOR = "│ "
_RAIL_SEPARATOR = "┃ "
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
class _GutterSection:
    """One section after its logical lines have been gutterized and wrapped."""

    text: Text
    row_count: int
    line_rows: tuple[int, ...]


def apply_gutter(
    text: Text,
    *,
    content_width: int,
    number_width: int,
    emphasis_range: tuple[int, int] | None = None,
    accent: str | None = None,
    change_marks: dict[int, str] | None = None,
    removal_anchors: set[int] | frozenset[int] | tuple[int, ...] | None = None,
    rail_style: str | None = None,
    history_styles: Any | None = None,
) -> _GutterSection:
    """Wrap *text* and prefix every visual row with gutter cells.

    ``line_rows`` maps each logical line (0-based) to its first visual row
    within the section. An empty body still occupies one visual row so
    layout never collapses, but it has no numbered lines to jump to.
    ``emphasis_range`` is an inclusive 1-based logical-line range: every
    visual row in that range, including wrapped continuation rows, paints
    a thick accent rail. The gutter cell count does not change.
    ``change_marks`` maps 1-based logical lines to ``"added"``/``"changed"``
    read-view marks; ``removal_anchors`` holds 1-based anchor rows where a
    red ``╴`` paints (0 means before-first). ``rail_style`` paints the
    plain ``│`` separator of every unmarked row — the past-accent rail
    for a pinned section. Precedence is goto emphasis, then change
    marks, then the rail: a goto rail wins when both a goto emphasis
    and a change mark coincide, and change marks win over the rail.
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
    lo, hi = _normalized_emphasis_range(emphasis_range)
    marks = change_marks or {}
    anchors = set(removal_anchors or ())
    mark_styles = _mark_styles(history_styles)
    lines = _logical_lines(text)
    visual_rows: list[Text] = []
    line_rows: list[int] = []
    if 0 in anchors:
        visual_rows.append(_removal_anchor_row(number_width, mark_styles[2]))
    for line_number, logical in enumerate(lines, start=1):
        line_rows.append(len(visual_rows))
        in_range = lo is not None and hi is not None and lo <= line_number <= hi
        wrapped = _wrap_logical_line(logical, wrap_width, console)
        for wrap_index, piece in enumerate(wrapped):
            number = line_number if wrap_index == 0 else None
            change_kind = marks.get(line_number) if wrap_index == 0 else None
            if in_range:
                visual_rows.append(
                    _guttered_row(
                        piece,
                        number=number,
                        number_width=number_width,
                        emphasize=in_range and number is not None,
                        rail=in_range,
                        accent=accent,
                    )
                )
            elif change_kind in ("added", "changed"):
                visual_rows.append(
                    _change_mark_row(
                        piece,
                        number=number,
                        number_width=number_width,
                        kind=change_kind,
                        mark_styles=mark_styles,
                    )
                )
            else:
                visual_rows.append(
                    _guttered_row(
                        piece,
                        number=number,
                        number_width=number_width,
                        emphasize=False,
                        rail=False,
                        accent=None,
                        rail_style=rail_style,
                    )
                )
        if line_number in anchors:
            visual_rows.append(_removal_anchor_row(number_width, mark_styles[2]))
    if not visual_rows:
        visual_rows.append(
            _guttered_row(
                Text(),
                number=None,
                number_width=number_width,
                emphasize=False,
                rail=False,
                accent=None,
                rail_style=rail_style,
            )
        )
    joined = Text(no_wrap=True, overflow="crop")
    for index, row in enumerate(visual_rows):
        if index:
            joined.append("\n")
        joined.append_text(row)
    return _GutterSection(
        text=joined,
        row_count=len(visual_rows),
        line_rows=tuple(line_rows),
    )


def _normalized_emphasis_range(
    emphasis_range: tuple[int, int] | None,
) -> tuple[int | None, int | None]:
    if emphasis_range is None:
        return None, None
    lo, hi = emphasis_range
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _wrap_logical_line(text: Text, width: int, console: Console) -> tuple[Text, ...]:
    if not text.plain:
        return (Text(),)
    copied = text.copy()
    copied.overflow = "fold"
    copied.no_wrap = False
    wrapped = tuple(copied.wrap(console, width, overflow="fold"))
    return wrapped if wrapped else (Text(),)


def _mark_styles(history_styles: Any | None) -> tuple[str, str, str]:
    """Return ``(added, changed, removal)`` gutter mark styles."""
    if history_styles is None:
        from sase.pager.history.styles import default_history_styles

        history_styles = default_history_styles()
    return (
        str(getattr(history_styles, "gutter_add", "green")),
        str(getattr(history_styles, "gutter_change", "blue")),
        str(getattr(history_styles, "gutter_remove", "red")),
    )


def _guttered_row(
    piece: Text,
    *,
    number: int | None,
    number_width: int,
    emphasize: bool,
    rail: bool,
    accent: str | None,
    rail_style: str | None = None,
) -> Text:
    row = Text(no_wrap=True, overflow="crop")
    row.append_text(
        _gutter_cells(
            number,
            number_width,
            emphasize=emphasize,
            rail=rail,
            accent=accent,
            rail_style=rail_style,
        )
    )
    row.append_text(piece)
    return row


def _gutter_cells(
    number: int | None,
    number_width: int,
    *,
    emphasize: bool,
    rail: bool,
    accent: str | None,
    rail_style: str | None = None,
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
    if rail:
        separator_style = accent if accent else "bold"
        cells.append(_RAIL_SEPARATOR, style=separator_style)
    elif rail_style is not None:
        cells.append(_SEPARATOR, style=rail_style)
    else:
        cells.append(_SEPARATOR, style=_SEPARATOR_STYLE)
    return cells


def _change_mark_row(
    piece: Text,
    *,
    number: int | None,
    number_width: int,
    kind: str,
    mark_styles: tuple[str, str, str] = ("green", "blue", "red"),
) -> Text:
    """Render one gutter row with a read-view change mark.

    Added ``▌`` uses the insert tone, changed ``▌`` the modified blue,
    and the removal ``╴`` the delete tone; the rail column is reused so
    gutter width never changes.
    """
    row = Text(no_wrap=True, overflow="crop")
    label = f"{'':>{number_width}}" if number is None else f"{number:>{number_width}}"
    row.append(label, style=_NUMBER_STYLE)
    if kind == "added":
        row.append("▌ ", style=mark_styles[0])
    else:
        row.append("▌ ", style=mark_styles[1])
    row.append_text(piece)
    return row


def _removal_anchor_row(number_width: int, style: str = "red") -> Text:
    """Render a removal-anchor row for deleted lines."""
    row = Text(no_wrap=True, overflow="crop")
    row.append(f"{'':>{number_width}}", style=_NUMBER_STYLE)
    row.append("╴ ", style=style)
    return row


__all__ = [
    "apply_gutter",
    "gutter_width",
    "logical_line_count",
    "number_width",
]
