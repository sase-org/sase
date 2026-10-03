"""Line-number gutter for pager section bodies.

Pure and Textual-free: prefix per-row gutter cells with exact row maps.
Wide characters use Rich cell math, never ``len()``.
"""

from __future__ import annotations

from typing import Any

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


def gutter_mark_styles(history_styles: Any | None = None) -> tuple[str, str, str]:
    """Return ``(added, changed, removal)`` gutter mark styles."""
    if history_styles is None:
        from sase.pager.history.styles import default_history_styles

        history_styles = default_history_styles()
    return (
        str(getattr(history_styles, "gutter_add", "green")),
        str(getattr(history_styles, "gutter_change", "blue")),
        str(getattr(history_styles, "gutter_remove", "red")),
    )


def gutter_row(
    piece: Text,
    *,
    number: int | None,
    number_width: int,
    rail: bool = False,
    emphasize: bool = False,
    accent: str | None = None,
    change_kind: str | None = None,
    mark_styles: tuple[str, str, str] = ("green", "blue", "red"),
    rail_style: str | None = None,
) -> Text:
    """Assemble one gutter-prefixed visual row for a wrapped line piece.

    A goto rail wins over change marks, and change marks win over the
    plain rail style. ``number`` is the 1-based logical line for a first
    wrap piece and ``None`` for continuations.
    """
    if rail:
        return _guttered_row(
            piece,
            number=number,
            number_width=number_width,
            emphasize=emphasize,
            rail=True,
            accent=accent,
        )
    if change_kind in ("added", "changed"):
        return _change_mark_row(
            piece,
            number=number,
            number_width=number_width,
            kind=change_kind,
            mark_styles=mark_styles,
        )
    return _guttered_row(
        piece,
        number=number,
        number_width=number_width,
        emphasize=False,
        rail=False,
        accent=None,
        rail_style=rail_style,
    )


def removal_anchor_row(number_width: int, style: str = "red") -> Text:
    """Render a removal-anchor row for deleted lines."""
    return _removal_anchor_row(number_width, style)


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
    "gutter_mark_styles",
    "gutter_row",
    "gutter_width",
    "logical_line_count",
    "number_width",
    "removal_anchor_row",
]
