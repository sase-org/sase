"""One DeckSpec record per agent data deck plus the active-deck accessor."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .model import DeckId

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeckSpec:
    """Static registry record describing one agent data deck."""

    deck_id: DeckId
    name: str
    glyph: str
    picker_key: str
    blurb: str
    count_noun: tuple[str, str]
    fallback_accent: str
    accent_class: str
    picker_class: str


DECK_SPECS: tuple[DeckSpec, ...] = (
    DeckSpec(
        deck_id=DeckId.MAIN,
        name="MAIN",
        glyph="\u25c6",
        picker_key="m",
        blurb="Context, prompt, and reply",
        count_noun=("card", "cards"),
        fallback_accent="#B48EAD",
        accent_class="-deck-main",
        picker_class="-deck-main",
    ),
    DeckSpec(
        deck_id=DeckId.FILES,
        name="FILES",
        glyph="\u25a4",
        picker_key="f",
        blurb="Diffs and files the agent touched",
        count_noun=("file", "files"),
        fallback_accent="green",
        accent_class="-deck-files",
        picker_class="-deck-files",
    ),
    DeckSpec(
        deck_id=DeckId.TOOLS,
        name="TOOLS",
        glyph="\u03bb",
        picker_key="t",
        blurb="LLM tool-call timeline",
        count_noun=("call", "calls"),
        fallback_accent="#87D7FF",
        accent_class="-deck-tools",
        picker_class="-deck-tools",
    ),
    DeckSpec(
        deck_id=DeckId.FINAL,
        name="FINAL",
        glyph="⊛",
        picker_key="n",
        blurb="how this node's turns landed",
        count_noun=("finalizer", "finalizers"),
        fallback_accent="#FF87D7",
        accent_class="-deck-final",
        picker_class="-deck-final",
    ),
)

_SPECS_BY_DECK: dict[DeckId, DeckSpec] = {s.deck_id: s for s in DECK_SPECS}


def deck_spec(deck: DeckId) -> DeckSpec:
    """Return the registry record for ``deck`` (raises ``KeyError``)."""
    return _SPECS_BY_DECK[deck]


def active_deck_cycle() -> tuple[DeckId, ...]:
    """Return the decks in cycle order (Main, Files, Tools, FINAL)."""
    return tuple(s.deck_id for s in DECK_SPECS)


def coerce_known_deck(deck: DeckId, *, context: str) -> DeckId:
    """Return ``deck`` when registered, else log and fall back to Main."""
    if deck in _SPECS_BY_DECK:
        return deck
    log.warning("Unknown deck %r in %s; falling back to Main", deck, context)
    return DeckId.MAIN


__all__ = [
    "DECK_SPECS",
    "DeckSpec",
    "active_deck_cycle",
    "coerce_known_deck",
    "deck_spec",
]
