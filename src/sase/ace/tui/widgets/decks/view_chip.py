"""Pure deck-view chip text variants."""

from __future__ import annotations

from rich.text import Text

from .model import DeckView
from .view_policy import ResolvedView, ViewStatus

VIEW_CHIP_STYLE = "bold #1a1a1a on #D0D0D0"

_MUTED = "#888888"
_WARNING = "#D7AF5F"

_LAYOUT_LONG: dict[DeckView, str] = {
    DeckView.SPREAD: "SPREAD",
    DeckView.PAGE_CARDS: "PAGE CARDS",
    DeckView.PAGE_BLOCKS: "PAGE BLOCKS",
}

_LAYOUT_SHORT: dict[DeckView, str] = {
    DeckView.SPREAD: "SPREAD",
    DeckView.PAGE_CARDS: "CARDS",
    DeckView.PAGE_BLOCKS: "BLOCKS",
}

_LAYOUT_TINY: dict[DeckView, str] = {
    DeckView.SPREAD: "S",
    DeckView.PAGE_CARDS: "C",
    DeckView.PAGE_BLOCKS: "B",
}

_LOCK = "\U0001f512"


def _layout_label(shown: DeckView, *, tiny: bool, short: bool) -> str:
    if shown not in _LAYOUT_LONG:
        shown = DeckView.SPREAD
    if tiny:
        return _LAYOUT_TINY[shown]
    if short:
        return _LAYOUT_SHORT[shown]
    return _LAYOUT_LONG[shown]


def _chip(label: str, *, locked: bool, tiny: bool, focused: bool) -> Text:
    """Return one padded chip; width does not depend on focus."""
    if locked:
        inner = f"{label}{_LOCK}" if tiny else f"{label} {_LOCK}"
    else:
        inner = label
    style = VIEW_CHIP_STYLE if focused else "dim"
    return Text(f" {inner} ", style=style)


def _status_words(
    resolved: ResolvedView, *, focused: bool
) -> tuple[Text | None, Text | None, Text | None]:
    """Return the (long, short, tiny) pending/blocked words, or Nones."""
    if resolved.status is ViewStatus.PENDING:
        words = ("spreading…", "spreading…", "…")
        style = _MUTED if focused else "dim"
    elif resolved.status is ViewStatus.BLOCKED:
        words = ("spread unavailable", "no spread", "!")
        style = _WARNING if focused else "dim"
    else:
        return (None, None, None)
    return (
        Text(words[0], style=style),
        Text(words[1], style=style),
        Text(words[2], style=style),
    )


def chip_variants(
    resolved: ResolvedView, *, accent: str, focused: bool
) -> tuple[Text, Text, Text, Text | None, Text | None, Text | None]:
    """Return long/short/tiny chips plus the pending/blocked word variants.

    Chips are padded one cell each side. A lock sits inside the chip before
    the trailing pad when the policy is not automatic. Pending and blocked
    words sit outside the chip and are returned separately.
    """
    del accent
    locked = resolved.policy is not DeckView.AUTO
    shown = resolved.shown
    long = _chip(
        _layout_label(shown, tiny=False, short=False),
        locked=locked,
        tiny=False,
        focused=focused,
    )
    short = _chip(
        _layout_label(shown, tiny=False, short=True),
        locked=locked,
        tiny=False,
        focused=focused,
    )
    tiny = _chip(
        _layout_label(shown, tiny=True, short=False),
        locked=locked,
        tiny=True,
        focused=focused,
    )
    word_long, word_short, word_tiny = _status_words(resolved, focused=focused)
    return (long, short, tiny, word_long, word_short, word_tiny)


__all__ = ["VIEW_CHIP_STYLE", "chip_variants"]
