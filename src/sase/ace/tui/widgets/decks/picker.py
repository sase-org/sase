"""Pure deck-picker model: no I/O, no Textual imports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .layout import is_zoomed
from .model import DECK_CYCLE, DeckAreaState, DeckId, DeckLayout
from .titles import (
    DECK_BLURBS,
    DECK_COUNT_NOUNS,
    DECK_GLYPHS,
    DECK_NAMES,
    DECK_PICKER_KEYS,
)

if TYPE_CHECKING:
    from .availability import DeckAvailability


def panel_position_label(state: DeckAreaState, panel_index: int) -> str:
    """Return the position label for ``panel_index``."""
    if is_zoomed(state):
        return "zoomed"
    if state.layout is DeckLayout.SINGLE:
        return "deck"
    if state.layout is DeckLayout.TOP_BOTTOM:
        return "top" if panel_index == 0 else "bottom"
    return "left" if panel_index == 0 else "right"


@dataclass(frozen=True)
class _OtherPanelTarget:
    """Where a capital deck letter sends the picked deck."""

    panel_index: int
    label: str
    opens_split: bool
    ends_zoom: bool


def other_panel_target(state: DeckAreaState, source_index: int) -> _OtherPanelTarget:
    """Resolve the "other panel" for a picker opened from ``source_index``.

    A single (or zoomed-from-single) deck area opens a new bottom panel. Any
    split, including one hidden behind a zoom, keeps its layout and targets
    the panel that is not ``source_index``.
    """
    base = state.zoom_snapshot if state.zoom_snapshot is not None else state
    ends_zoom = is_zoomed(state)
    if base.layout is DeckLayout.SINGLE:
        return _OtherPanelTarget(
            panel_index=1, label="bottom", opens_split=True, ends_zoom=ends_zoom
        )
    panel_index = 1 - min(max(source_index, 0), 1)
    return _OtherPanelTarget(
        panel_index=panel_index,
        label=panel_position_label(base, panel_index),
        opens_split=False,
        ends_zoom=ends_zoom,
    )


def deck_picker_other_hint(target: _OtherPanelTarget) -> str:
    """Return the phrase telling where a capital deck letter goes."""
    phrase = (
        "open in a new bottom panel"
        if target.opens_split
        else f"show in the {target.label} panel"
    )
    return f"{phrase} · ends zoom" if target.ends_zoom else phrase


@dataclass(frozen=True)
class DeckPick:
    """The deck the picker chose and whether it goes to the other panel."""

    deck: DeckId
    other_panel: bool


@dataclass(frozen=True)
class DeckPickerState:
    """Snapshot the picker acts on."""

    panel_index: int
    panel_label: str
    current: DeckId
    other: tuple[DeckId, str] | None
    availability: Mapping[DeckId, DeckAvailability]
    accents: Mapping[DeckId, str]
    other_target: _OtherPanelTarget | None = None


@dataclass(frozen=True)
class DeckPickerRow:
    """One picker row in DECK_CYCLE order."""

    deck: DeckId
    key: str
    glyph: str
    name: str
    accent: str
    count_label: str
    blurb: str
    has_content: bool | None
    is_current: bool
    other_panel_label: str | None


def _deck_count_label(deck: DeckId, availability: object | None) -> str:
    """Return the count label for ``deck``."""
    from .availability import DeckAvailability

    if not isinstance(availability, DeckAvailability):
        return ""
    if availability.has_content is False:
        return "empty"
    if availability.count is None:
        return ""
    singular, plural = DECK_COUNT_NOUNS[deck]
    count = availability.count
    noun = singular if count == 1 else plural
    return f"{count} {noun}"


def deck_picker_heading(state: DeckPickerState) -> str:
    """Return the picker heading for ``state``."""
    if state.panel_label == "deck":
        return "Choose what the deck panel shows"
    return f"Choose what the {state.panel_label} panel shows"


def build_deck_picker_rows(state: DeckPickerState) -> tuple[DeckPickerRow, ...]:
    """Build picker rows in DECK_CYCLE order."""
    rows: list[DeckPickerRow] = []
    for deck in DECK_CYCLE:
        avail = state.availability.get(deck)
        has_content = getattr(avail, "has_content", None)
        other_label: str | None = None
        if state.other is not None and state.other[0] is deck:
            other_label = state.other[1]
        rows.append(
            DeckPickerRow(
                deck=deck,
                key=DECK_PICKER_KEYS[deck],
                glyph=DECK_GLYPHS[deck],
                name=DECK_NAMES[deck],
                accent=state.accents.get(deck, ""),
                count_label=_deck_count_label(deck, avail),
                blurb=DECK_BLURBS[deck],
                has_content=has_content,
                is_current=deck is state.current,
                other_panel_label=other_label,
            )
        )
    return tuple(rows)


__all__ = [
    "DeckPick",
    "DeckPickerRow",
    "DeckPickerState",
    "build_deck_picker_rows",
    "deck_picker_heading",
    "deck_picker_other_hint",
    "other_panel_target",
    "panel_position_label",
]
