"""Geometry for the floating completion popup (pure, Textual-free).

The popup floats over the transcript, docked just above the input row, and
its left edge follows the completion slot: the candidate text lines up with
the span it will replace, as in Helix. Widths come from the candidates
themselves, so the card is as wide as its widest row; the whole float (card
plus the doc-peek beside it) is then clamped inside the frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.cells import cell_len

#: Cells between the card's left edge and the candidate text: the card
#: border (1) plus the entity glyph and its space (2).
POPUP_TEXT_INSET = 3

#: Rows below the popup that it must never cover: the input row (3) and the
#: signature/hint row (1).
POPUP_BOTTOM_RESERVE = 4

#: Card width bounds, in cells (border included).
POPUP_MIN_WIDTH = 34
POPUP_MAX_WIDTH = 100

#: Widest the doc-peek card may grow, and the gap between it and the popup.
PEEK_MAX_WIDTH = 60
PEEK_GAP = 1

#: Chrome cells around a candidate row's content: glyph (2) + card border (2).
_ROW_CHROME = 4

#: Candidate rows measured for the width; the popup never lists more.
_MEASURED_ROWS = 200


@dataclass(frozen=True, slots=True)
class _PopupGeometry:
    """Where the floating popup sits, in frame-content cells."""

    #: Left edge of the float (the popup card).
    x: int
    #: Card width, border included.
    card_width: int
    #: Doc-peek width, border included; ``0`` when it does not fit.
    peek_width: int


def popup_content_width(items: list[dict[str, Any]]) -> int:
    """Return the widest candidate row's width in cells, chrome included.

    Mirrors the row layout of ``popup._render_popup_row`` (glyph, value,
    ``[badge]``, description, ``sel`` marker) without building any ``Text``.
    """
    widest = 0
    for item in items[:_MEASURED_ROWS]:
        display = str(item.get("display", "") or item.get("insert_text", ""))
        width = _ROW_CHROME + cell_len(display)
        badge = str(item.get("badge", "") or "")
        if badge:
            width += cell_len(badge) + 4
        description = str(item.get("description", "") or "")
        if description:
            width += cell_len(description) + 2
        if item.get("selected"):
            width += 5
        widest = max(widest, width)
    return widest


def popup_geometry(
    *, anchor: int, content: int, peek: int, available: int
) -> _PopupGeometry:
    """Clamp the popup float inside *available* frame-content columns.

    *anchor* is the replace-span column, *content* the widest row from
    :func:`popup_content_width`, and *peek* the doc-peek's natural width
    (``0`` for none). The card shrinks before the peek does; the peek is
    dropped when even a minimum-width card leaves it no room.
    """
    card = min(max(content, POPUP_MIN_WIDTH), POPUP_MAX_WIDTH, max(available, 1))
    peek_width = min(peek, PEEK_MAX_WIDTH) if peek > 0 else 0
    if peek_width:
        room = available - PEEK_GAP - peek_width
        if room >= POPUP_MIN_WIDTH:
            card = min(card, room)
        else:
            peek_width = 0
    total = card + (PEEK_GAP + peek_width if peek_width else 0)
    x = min(max(anchor - POPUP_TEXT_INSET, 0), max(available - total, 0))
    return _PopupGeometry(x=x, card_width=card, peek_width=peek_width)


__all__ = [
    "PEEK_GAP",
    "POPUP_BOTTOM_RESERVE",
    "POPUP_MAX_WIDTH",
    "POPUP_MIN_WIDTH",
    "POPUP_TEXT_INSET",
    "popup_content_width",
    "popup_geometry",
]
