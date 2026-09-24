"""Pure deck title and subtitle helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

from .model import DECK_CYCLE, DeckId

DECK_GLYPHS: dict[DeckId, str] = {
    DeckId.MAIN: "\u25c6",
    DeckId.FILES: "\u25a4",
    DeckId.TOOLS: "\u03bb",
}

DECK_NAMES: dict[DeckId, str] = {
    DeckId.MAIN: "MAIN",
    DeckId.FILES: "FILES",
    DeckId.TOOLS: "TOOLS",
}

DECK_ACCENTS: dict[DeckId, str] = {
    DeckId.MAIN: "$secondary",
    DeckId.FILES: "green",
    DeckId.TOOLS: "#87D7FF",
}

_MUTED = "#888888"
_SEPARATOR = "#444444"


@dataclass(frozen=True)
class CardTab:
    """One tab in a deck title strip."""

    card_id: str
    title: str


def _plain_width(text: Text) -> int:
    return cell_len(text.plain)


def _build_full(
    deck: DeckId,
    tabs: Sequence[CardTab],
    active_index: int | None,
    *,
    accent: str,
    focused: bool,
) -> Text:
    text = Text()
    glyph = DECK_GLYPHS[deck]
    name = DECK_NAMES[deck]
    if focused:
        text.append(f"{glyph} {name} ", style=f"bold {accent}")
    else:
        text.append(f"{glyph} {name} ", style="dim")
    text.append("\u2503", style=_SEPARATOR)
    text.append(" ", style="")
    for i, tab in enumerate(tabs):
        if i > 0:
            text.append(" \u2502 ", style=_SEPARATOR)
        if active_index is not None and i == active_index:
            if focused:
                text.append(tab.title, style=f"reverse bold {accent}")
            else:
                text.append(tab.title, style="dim")
        else:
            text.append(tab.title, style=_MUTED)
    if active_index is not None and len(tabs) > 1:
        text.append(f"  {active_index + 1}/{len(tabs)}", style=_MUTED)
    return text


def _build_compact(
    deck: DeckId,
    tabs: Sequence[CardTab],
    active_index: int | None,
    *,
    accent: str,
    focused: bool,
) -> Text:
    text = Text()
    glyph = DECK_GLYPHS[deck]
    name = DECK_NAMES[deck]
    if focused:
        text.append(f"{glyph} {name} ", style=f"bold {accent}")
    else:
        text.append(f"{glyph} {name} ", style="dim")
    text.append("\u2503", style=_SEPARATOR)
    text.append(" ", style="")
    if active_index is not None and 0 <= active_index < len(tabs):
        if len(tabs) > 1:
            text.append(f"\u2039 {active_index + 1}/{len(tabs)} \u203a ", style=_MUTED)
        text.append(
            tabs[active_index].title, style=f"bold {accent}" if focused else "dim"
        )
    elif tabs:
        text.append(tabs[0].title, style=_MUTED)
    return text


def _build_micro(
    deck: DeckId,
    tabs: Sequence[CardTab],
    active_index: int | None,
    *,
    accent: str,
    focused: bool,
) -> Text:
    del accent
    del focused
    text = Text()
    text.append(DECK_NAMES[deck], style=_MUTED)
    if active_index is not None and len(tabs) > 1:
        text.append(f" {active_index + 1}/{len(tabs)}", style=_MUTED)
    return text


def deck_title(
    deck: DeckId,
    tabs: Sequence[CardTab],
    active_index: int | None,
    *,
    width: int,
    accent: str,
    focused: bool,
) -> Text:
    """Render a deck title tab strip, picking the widest fitting tier."""
    tabs = tuple(tabs)
    # Files full tier lists all tabs only when there are 4 or fewer.
    use_compact_full = deck is DeckId.FILES and len(tabs) > 4
    candidates: list[tuple[str, Text]]
    if use_compact_full:
        candidates = [
            (
                "compact",
                _build_compact(
                    deck, tabs, active_index, accent=accent, focused=focused
                ),
            ),
            (
                "micro",
                _build_micro(deck, tabs, active_index, accent=accent, focused=focused),
            ),
        ]
    else:
        candidates = [
            (
                "full",
                _build_full(deck, tabs, active_index, accent=accent, focused=focused),
            ),
            (
                "compact",
                _build_compact(
                    deck, tabs, active_index, accent=accent, focused=focused
                ),
            ),
            (
                "micro",
                _build_micro(deck, tabs, active_index, accent=accent, focused=focused),
            ),
        ]
    if width <= 0:
        return candidates[0][1]
    for _tier, rendered in candidates:
        if _plain_width(rendered) <= width:
            return rendered
    return candidates[-1][1]


def deck_subtitle(
    active: DeckId,
    availability: Mapping[DeckId, object],
    *,
    status: Text | None,
    width: int,
    accent_for: Mapping[DeckId, str],
    spread: bool = False,
) -> Text:
    """Render the deck switcher with an optional leading status."""
    from .availability import DeckAvailability

    parts: list[tuple[str, str]] = []
    for deck in DECK_CYCLE:
        label = deck.value
        avail = availability.get(deck)
        count: int | None = None
        has_content: bool | None = None
        if isinstance(avail, DeckAvailability):
            has_content = avail.has_content
            count = avail.count
        if deck is active:
            style = f"bold {accent_for.get(deck, '')}".strip()
        elif has_content is False:
            style = "dim"
        else:
            style = ""
        display = label
        if isinstance(avail, DeckAvailability) and avail.count is not None:
            display = f"{label} {count}"
        parts.append((display, style))
    switcher = Text()
    for i, (display, style) in enumerate(parts):
        if i > 0:
            switcher.append(" \u00b7 ", style=_MUTED)
        switcher.append(display, style=style)
    spread_tag = Text("spread", style="dim") if spread else None
    if status is None and spread_tag is None:
        combined = switcher
        if width > 0 and _plain_width(combined) > width:
            return Text(combined.plain[: max(0, width)], style="")
        return combined
    if status is None:
        assert spread_tag is not None
        full = Text()
        full.append_text(spread_tag)
        full.append("  ", style="")
        full.append_text(switcher)
        if width <= 0 or _plain_width(full) <= width:
            return full
        # Drop the spread tag first when width is tight.
        if _plain_width(switcher) <= width or width <= 0:
            return switcher
        return Text(switcher.plain[: max(0, width)], style="")
    full = Text()
    full.append_text(status)
    if spread_tag is not None:
        full.append("  ", style="")
        full.append_text(spread_tag)
    full.append("  ", style="")
    full.append_text(switcher)
    if width <= 0 or _plain_width(full) <= width:
        return full
    # Drop the spread tag first when width is tight.
    if spread_tag is not None:
        without_spread = Text()
        without_spread.append_text(status)
        without_spread.append("  ", style="")
        without_spread.append_text(switcher)
        if _plain_width(without_spread) <= width:
            return without_spread
    # Drop the switcher first, then truncate the status.
    status_only = Text()
    status_only.append_text(status)
    if _plain_width(status_only) <= width:
        return status_only
    truncated = status_only.plain[: max(0, width)]
    return Text(truncated, style="")


def file_line_status(
    visible: int, total: int, capped: bool, *, editor_key: str
) -> Text | None:
    """Render the Files line-count status, or None when there are no lines."""
    if total == 0:
        return None
    if capped:
        return Text(
            f"1-{visible} of {total} lines \u00b7 {editor_key} editor", style=""
        )
    return Text(f"{total} lines", style="")
