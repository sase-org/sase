"""Titled separators between spread deck cards."""

from __future__ import annotations

from typing import Any

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions
from rich.measure import Measurement
from rich.segment import Segment
from rich.style import Style

from .model import DeckId
from .spec import deck_spec
from ..prompt_panel._section_navigation import DECK_CARD_META_KEY


class _CardSeparator:
    """One full-width titled rule between consecutive spread cards."""

    def __init__(
        self,
        card_id: str,
        title: str,
        *,
        glyph: str | None = None,
        accent: str = "",
    ) -> None:
        self.card_id = card_id
        self.title = title
        self.glyph = glyph if glyph is not None else ""
        self.accent = accent

    def _rule_text(self, width: int) -> str:
        width = max(1, int(width))
        if self.glyph:
            prefix = f"━━ {self.glyph} {self.title} "
        else:
            prefix = f"━━ {self.title} " if self.title else "━━ "
        prefix_len = cell_len(prefix)
        if prefix_len >= width:
            # Truncate the title, never raise.
            truncated = prefix[: max(0, width)]
            # Cell-width truncation may still overshoot on wide chars; clamp.
            while cell_len(truncated) > width and truncated:
                truncated = truncated[:-1]
            return truncated
        fill = "━" * (width - prefix_len)
        return f"{prefix}{fill}"

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> Any:
        from rich.text import Text

        width = max(1, int(options.max_width))
        yield Text("")
        text = self._rule_text(width)
        try:
            if self.accent and not self.accent.startswith("$"):
                style = Style(
                    color=self.accent, meta={DECK_CARD_META_KEY: self.card_id}
                )
            else:
                style = Style(meta={DECK_CARD_META_KEY: self.card_id})
        except Exception:
            style = Style(meta={DECK_CARD_META_KEY: self.card_id})
        yield Segment(text, style)
        yield Segment("\n")

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        width = max(1, int(options.max_width))
        return Measurement(width, width)


def card_separator_for(
    deck: DeckId, card: Any, *, accent: str | None = None
) -> _CardSeparator:
    """Build a spread separator for ``card`` on any card-document deck."""
    spec = deck_spec(deck)
    try:
        card_id = str(card.card_id)
    except Exception:
        card_id = ""
    try:
        title = str(card.title)
    except Exception:
        title = ""
    if accent is None:
        accent = spec.fallback_accent
    return _CardSeparator(card_id, title, glyph=spec.glyph, accent=accent)


def files_separator_for(card_id: str, title: str) -> _CardSeparator:
    """Build a Files-deck separator with the deck glyph and accent."""
    files = deck_spec(DeckId.FILES)
    return _CardSeparator(
        card_id, title, glyph=files.glyph, accent=files.fallback_accent
    )


__all__ = [
    "card_separator_for",
    "files_separator_for",
]
