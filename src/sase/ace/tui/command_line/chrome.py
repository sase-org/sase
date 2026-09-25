"""Border chrome for the Command Line frame.

The title, working-context chip, key hints and running count live on the
frame's borders instead of rows inside it: the top border carries
``❯ Command Line`` on its left and the chip on its right, the bottom border
carries the context key hints on its left and ``N running`` on its right.

Textual draws one label per border edge (``border_title`` on top,
``border_subtitle`` on the bottom), so each edge is a padded composed label:
left text, a run of border dashes, right text. The frame recomposes both
labels whenever its width changes, so the two ends stay aligned and the chip
is middle-truncated to whatever room the title leaves.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import Vertical
from textual.message import Message

from sase.ace.tui.command_line.context import middle_truncate

#: Cells Textual reserves on a border edge around its label: two corners plus
#: one blank on each side of the label.
_LABEL_RESERVE = 4

#: Cells the composed label leaves free so a border dash shows on both sides
#: of it (``╭─ ❯ Command Line … ─╮``).
_LABEL_MARGIN = 2

#: Blanks around the run of border dashes between the two labels.
_FILL_PADDING = 2

#: Fewest cells a right label may keep before it is dropped entirely.
_MIN_RIGHT_CELLS = 6


def _title_label() -> Text:
    """Return the top-left title: a bold gold ``❯`` and a bold name."""
    label = Text()
    label.append("❯", style="bold #FFD700")
    label.append(" Command Line", style="bold")
    return label


def _fit_label(label: Text, width: int, *, middle: bool) -> Text:
    """Shrink *label* to *width* cells, eliding its end (or its middle).

    Middle elision restyles the shortened text with the label's base style, so
    it suits single-style labels such as the context chip.
    """
    if label.cell_len <= width:
        return label
    if middle:
        return Text(middle_truncate(label.plain, width), style=label.style)
    fitted = label.copy()
    fitted.truncate(width, overflow="ellipsis")
    return fitted


def _compose_border_label(
    left: Text,
    right: Text,
    width: int,
    *,
    fill_style: str = "",
    middle_right: bool = False,
    keep_right: bool = False,
) -> Text:
    """Compose one border label spanning *width* cells: left, dashes, right.

    By default the left text has priority: the right text keeps whatever room
    it leaves, elided from its end (or its middle with *middle_right*), and
    is dropped when fewer than a handful of cells remain. With *keep_right*
    the right text is whole and the left text gives way instead, ellipsized
    or dropped. A label with no right text is returned unpadded: Textual
    fills the rest of the edge itself.
    """
    if width <= 0:
        return Text()
    if not right.plain:
        return _fit_label(left, width, middle=False)
    if keep_right:
        right = _fit_label(right, width - _FILL_PADDING - 1, middle=middle_right)
        room = width - right.cell_len - _FILL_PADDING - 1
        left = _fit_label(left, room, middle=False) if room >= 1 else Text()
    else:
        room = width - left.cell_len - _FILL_PADDING - 1
        if room < _MIN_RIGHT_CELLS:
            return _fit_label(left, width, middle=False)
        right = _fit_label(right, room, middle=middle_right)
    fill = width - left.cell_len - right.cell_len - (_FILL_PADDING if left.plain else 1)
    composed = left.copy()
    if left.plain:
        composed.append(" ")
    composed.append("─" * fill, style=fill_style)
    composed.append(" ")
    composed.append_text(right)
    return composed


class CommandLineFrame(Vertical):
    """The panel frame; its borders carry the title, chip, hints and count."""

    class Resized(Message):
        """The frame's size changed, so anything laid out against it is stale."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._chip = ""
        self._hints = ""
        self._running_count = 0
        #: The last composed labels (empty until the first layout pass).
        self.top_label = Text()
        self.bottom_label = Text()

    def set_chip(self, chip: str) -> None:
        """Set the working-context chip on the top border's right."""
        if chip != self._chip:
            self._chip = chip
            self._compose_labels()

    def set_key_hints(self, hints: str) -> None:
        """Set the context key hints on the bottom border's left."""
        if hints != self._hints:
            self._hints = hints
            self._compose_labels()

    def set_running_count(self, count: int) -> None:
        """Set the ``N running`` count on the bottom border's right."""
        if count != self._running_count:
            self._running_count = count
            self._compose_labels()

    def on_resize(self) -> None:
        self._compose_labels()
        self.post_message(self.Resized())

    def _fill_style(self) -> str:
        """Return the frame's own border color, so the dashes match the edge."""
        try:
            return self.styles.border_top[1].hex6
        except Exception:  # noqa: BLE001 - an unstyled border keeps default dashes.
            return ""

    def _compose_labels(self) -> None:
        """Recompose both border labels for the current width."""
        width = self.outer_size.width - _LABEL_RESERVE - _LABEL_MARGIN
        if width <= 0:
            return  # Not laid out yet; the first resize composes them.
        fill_style = self._fill_style()
        self.top_label = _compose_border_label(
            _title_label(),
            Text(self._chip),
            width,
            fill_style=fill_style,
            middle_right=True,
        )
        self.bottom_label = _compose_border_label(
            Text(self._hints),
            Text(f"{self._running_count} running"),
            width,
            fill_style=fill_style,
            keep_right=True,
        )
        self.border_title = self.top_label
        self.border_subtitle = self.bottom_label


__all__ = ["CommandLineFrame"]
