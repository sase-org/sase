"""Spread-title rungs, one-card headings, and view-chip assembly."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from rich.text import Text

from .model import DeckId
from .spec import DECK_SPECS
from .view_chip import chip_variants
from .view_policy import ResolvedView, ViewStatus

_MUTED = "#888888"
_SEPARATOR = "#444444"
_ARROW_UP = "\u25b4"
_ARROW_DOWN = "\u25be"

_DECK_GLYPHS: dict[DeckId, str] = {spec.deck_id: spec.glyph for spec in DECK_SPECS}
_DECK_NAMES: dict[DeckId, str] = {spec.deck_id: spec.name for spec in DECK_SPECS}


class _HasTitle(Protocol):
    @property
    def title(self) -> str: ...


@dataclass(frozen=True)
class SpreadCue:
    """Cards around the you-are-here title in a spread deck.

    ``above`` / ``below`` are card titles in document order. ``all_in_view``
    is reserved for the viewport-cues phase; structural cues leave it false.
    """

    here: str
    above: tuple[str, ...] = ()
    below: tuple[str, ...] = ()
    all_in_view: bool = False


def _card_noun(deck: DeckId, count: int) -> str:
    """Return the spread-cue noun for ``deck`` (never ``DeckSpec.count_noun``)."""
    stem = "file" if deck is DeckId.FILES else "card"
    return stem if count == 1 else f"{stem}s"


def structural_spread_cue(
    tabs: Sequence[_HasTitle], active_index: int | None
) -> SpreadCue | None:
    """Return the structural cue from tab order, or None when empty."""
    if not tabs:
        return None
    if active_index is None or not 0 <= active_index < len(tabs):
        active_index = 0
    here = tabs[active_index].title
    above = tuple(tab.title for tab in tabs[:active_index])
    below = tuple(tab.title for tab in tabs[active_index + 1 :])
    return SpreadCue(here=here, above=above, below=below)


def _chip_is_visible(deck: DeckId, view: ResolvedView | None) -> bool:
    """Return whether Main/Files should draw the view chip."""
    if view is None:
        return False
    if deck is not DeckId.MAIN and deck is not DeckId.FILES:
        return False
    if view.status is ViewStatus.PENDING or view.status is ViewStatus.BLOCKED:
        return True
    return bool(view.choice_exists)


def _attach_word(chip: Text, word: Text | None) -> Text:
    if word is None or not word.plain:
        return chip
    combined = Text()
    combined.append_text(chip)
    combined.append(" ", style="")
    combined.append_text(word)
    return combined


def chip_set(
    deck: DeckId,
    view: ResolvedView | None,
    *,
    accent: str,
    focused: bool,
) -> tuple[Text | None, Text | None, Text | None]:
    """Return the (long, short, tiny) chip-plus-word Texts, or Nones."""
    if not _chip_is_visible(deck, view):
        return (None, None, None)
    assert view is not None
    long, short, tiny, word_long, word_short, word_tiny = chip_variants(
        view, accent=accent, focused=focused
    )
    return (
        _attach_word(long, word_long),
        _attach_word(short, word_short),
        _attach_word(tiny, word_tiny),
    )


def append_deck_name(
    text: Text,
    deck: DeckId,
    *,
    accent: str,
    focused: bool,
    badge: Text | None = None,
) -> None:
    """Append ``glyph NAME`` plus the optional view chip after it."""
    glyph = _DECK_GLYPHS[deck]
    name = _DECK_NAMES[deck]
    if focused:
        text.append(f"{glyph} {name} ", style=f"bold {accent}")
    else:
        text.append(f"{glyph} {name} ", style="dim")
    if badge is not None:
        text.append_text(badge)
        text.append(" ", style="")


def _all_in_view_phrase(deck: DeckId, count: int, *, compact: bool) -> str:
    """Return the all-in-view copy, or empty when the phrase is dropped."""
    if count < 1:
        return ""
    if compact:
        return "all in view"
    noun = _card_noun(deck, count)
    if count == 2:
        return f"both {noun} in view"
    return f"all {count} {noun} in view"


def _focused_or_dim(style: str, *, focused: bool) -> str:
    return style if focused else "dim"


def _append_sep(text: Text, *, focused: bool) -> None:
    if text.plain:
        text.append(" · ", style=_focused_or_dim(_SEPARATOR, focused=focused))


def _append_direction(
    text: Text,
    arrow: str,
    titles: tuple[str, ...],
    deck: DeckId,
    *,
    accent: str,
    focused: bool,
    named: bool,
) -> None:
    if not titles:
        return
    _append_sep(text, focused=focused)
    text.append(arrow, style=_focused_or_dim(f"bold {accent}", focused=focused))
    if named and len(titles) == 1:
        text.append(" ", style="")
        text.append(titles[0], style=_focused_or_dim(_MUTED, focused=focused))
        return
    text.append(" ", style="")
    if named:
        count = len(titles)
        text.append(
            f"{count} {_card_noun(deck, count)}",
            style=_focused_or_dim(_MUTED, focused=focused),
        )
        return
    text.append(str(len(titles)), style=_focused_or_dim(_MUTED, focused=focused))


def _cue_body(
    deck: DeckId,
    cue: SpreadCue,
    *,
    accent: str,
    focused: bool,
    include_here: bool,
    named: bool,
    compact_all_in_view: bool = False,
) -> Text:
    total = (1 if cue.here else 0) + len(cue.above) + len(cue.below)
    if cue.all_in_view or not (cue.above or cue.below):
        phrase = _all_in_view_phrase(
            deck, total, compact=compact_all_in_view or not include_here
        )
        text = Text()
        if phrase:
            text.append(phrase, style=_focused_or_dim(_MUTED, focused=focused))
        return text
    text = Text()
    if include_here and cue.here:
        text.append(cue.here, style=_focused_or_dim(f"bold {accent}", focused=focused))
    _append_direction(
        text,
        _ARROW_UP,
        cue.above,
        deck,
        accent=accent,
        focused=focused,
        named=named,
    )
    _append_direction(
        text,
        _ARROW_DOWN,
        cue.below,
        deck,
        accent=accent,
        focused=focused,
        named=named,
    )
    return text


def _arrows_only(cue: SpreadCue, *, accent: str, focused: bool) -> Text:
    text = Text()
    style = _focused_or_dim(f"bold {accent}", focused=focused)
    if cue.above:
        text.append(_ARROW_UP, style=style)
    if cue.below:
        text.append(_ARROW_DOWN, style=style)
    return text


def _prefixed(
    deck: DeckId,
    badge: Text | None,
    body: Text,
    *,
    accent: str,
    focused: bool,
    micro: bool,
) -> Text:
    text = Text()
    if micro:
        text.append(_DECK_NAMES[deck], style=_MUTED)
        if badge is not None:
            text.append(" ", style="")
            text.append_text(badge)
            text.append(" ", style="")
        elif body.plain:
            text.append(" ", style="")
    else:
        append_deck_name(text, deck, accent=accent, focused=focused, badge=badge)
    if body.plain:
        text.append_text(body)
    return text


def one_card_candidates(
    deck: DeckId,
    tabs: Sequence[_HasTitle],
    *,
    accent: str,
    focused: bool,
) -> list[Text]:
    """Return the one-card heading rungs (no tabs, no chip)."""
    title = tabs[0].title if tabs else ""
    name_style = f"bold {accent}" if focused else "dim"
    full = Text()
    full.append(f"{_DECK_GLYPHS[deck]} {_DECK_NAMES[deck]}", style=name_style)
    if title:
        full.append("  ", style="")
        full.append(title, style=name_style)
    micro = Text()
    micro.append(_DECK_NAMES[deck], style=_MUTED)
    if title:
        micro.append("  ", style="")
        micro.append(title, style=_MUTED)
    return [full, micro]


def spread_title_candidates(
    deck: DeckId,
    cue: SpreadCue,
    chips: tuple[Text | None, Text | None, Text | None],
    *,
    accent: str,
    focused: bool,
) -> list[Text]:
    """Return the spread ladder: first rung that fits wins."""
    long_chip, _short_chip, tiny_chip = chips
    here_named = _cue_body(
        deck, cue, accent=accent, focused=focused, include_here=True, named=True
    )
    named = _cue_body(
        deck, cue, accent=accent, focused=focused, include_here=False, named=True
    )
    counted = _cue_body(
        deck, cue, accent=accent, focused=focused, include_here=False, named=False
    )
    compact_all = _cue_body(
        deck,
        cue,
        accent=accent,
        focused=focused,
        include_here=False,
        named=True,
        compact_all_in_view=True,
    )
    arrows = _arrows_only(cue, accent=accent, focused=focused)
    all_in_view = cue.all_in_view or not (cue.above or cue.below)
    if all_in_view:
        return [
            _prefixed(
                deck, long_chip, here_named, accent=accent, focused=focused, micro=False
            ),
            _prefixed(
                deck,
                long_chip,
                compact_all,
                accent=accent,
                focused=focused,
                micro=False,
            ),
            _prefixed(
                deck, long_chip, Text(), accent=accent, focused=focused, micro=False
            ),
            _prefixed(
                deck, tiny_chip, Text(), accent=accent, focused=focused, micro=False
            ),
            _prefixed(
                deck, tiny_chip, Text(), accent=accent, focused=focused, micro=True
            ),
            _prefixed(deck, None, Text(), accent=accent, focused=focused, micro=True),
        ]
    return [
        _prefixed(
            deck, long_chip, here_named, accent=accent, focused=focused, micro=False
        ),
        _prefixed(deck, long_chip, named, accent=accent, focused=focused, micro=False),
        _prefixed(
            deck, long_chip, counted, accent=accent, focused=focused, micro=False
        ),
        _prefixed(deck, tiny_chip, arrows, accent=accent, focused=focused, micro=False),
        _prefixed(deck, tiny_chip, arrows, accent=accent, focused=focused, micro=True),
        _prefixed(deck, None, arrows, accent=accent, focused=focused, micro=True),
    ]


__all__ = [
    "SpreadCue",
    "append_deck_name",
    "chip_set",
    "one_card_candidates",
    "spread_title_candidates",
    "structural_spread_cue",
]
