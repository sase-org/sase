"""Pure deck-view badge text variants."""

from __future__ import annotations

from rich.text import Text

from .model import DeckView
from .view_policy import ResolvedView, ViewStatus

_MUTED = "#888888"
_SEPARATOR = "#444444"
_WARNING = "#D7AF5F"

_LAYOUT_LONG: dict[DeckView, str] = {
    DeckView.SPREAD: "spread",
    DeckView.PAGE_CARDS: "page cards",
    DeckView.PAGE_BLOCKS: "page blocks",
}

_LAYOUT_SHORT: dict[DeckView, str] = {
    DeckView.SPREAD: "spread",
    DeckView.PAGE_CARDS: "cards",
    DeckView.PAGE_BLOCKS: "blocks",
}

_LAYOUT_TINY: dict[DeckView, str] = {
    DeckView.SPREAD: "S",
    DeckView.PAGE_CARDS: "C",
    DeckView.PAGE_BLOCKS: "B",
}


def _status_texts(resolved: ResolvedView) -> tuple[str, str, str]:
    """Return the (long, short, tiny) status words for ``resolved``."""
    if resolved.status is ViewStatus.PENDING:
        return ("spreading…", "spreading…", "…")
    if resolved.status is ViewStatus.BLOCKED:
        return ("spread unavailable", "no spread", "!")
    if resolved.policy is DeckView.AUTO:
        return ("auto", "auto", "A")
    return ("fixed", "fixed", "F")


def _layout_texts(shown: DeckView) -> tuple[str, str, str]:
    """Return the (long, short, tiny) layout words for ``shown``."""
    if shown is DeckView.AUTO:
        return ("auto", "auto", "A")
    return (
        _LAYOUT_LONG[shown],
        _LAYOUT_SHORT[shown],
        _LAYOUT_TINY[shown],
    )


def _status_style(resolved: ResolvedView, *, accent: str, focused: bool) -> str:
    """Return the status segment style."""
    if not focused:
        return "dim"
    if resolved.status is ViewStatus.BLOCKED:
        return _WARNING
    if resolved.status is ViewStatus.PENDING:
        return _MUTED
    if resolved.policy is DeckView.AUTO:
        return _MUTED
    return f"bold {accent}"


def _build(
    layout_word: str,
    status_word: str,
    *,
    joiner: str,
    accent: str,
    focused: bool,
    status_style: str,
) -> Text:
    text = Text()
    if focused:
        text.append(layout_word, style=accent)
        text.append(joiner, style=_SEPARATOR)
        text.append(status_word, style=status_style)
    else:
        text.append(layout_word, style="dim")
        text.append(joiner, style="dim")
        text.append(status_word, style="dim")
    return text


def badge_variants(
    resolved: ResolvedView, *, accent: str, focused: bool
) -> tuple[Text, Text, Text]:
    """Return the (long, short, tiny) badge variants for ``resolved``.

    Long and short join as ``{layout} · {status}``; tiny joins as
    ``{layout}·{status}``.
    """
    layout_long, layout_short, layout_tiny = _layout_texts(resolved.shown)
    status_long, status_short, status_tiny = _status_texts(resolved)
    status_style = _status_style(resolved, accent=accent, focused=focused)
    return (
        _build(
            layout_long,
            status_long,
            joiner=" · ",
            accent=accent,
            focused=focused,
            status_style=status_style,
        ),
        _build(
            layout_short,
            status_short,
            joiner=" · ",
            accent=accent,
            focused=focused,
            status_style=status_style,
        ),
        _build(
            layout_tiny,
            status_tiny,
            joiner="·",
            accent=accent,
            focused=focused,
            status_style=status_style,
        ),
    )


__all__ = ["badge_variants"]
