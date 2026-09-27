"""Spec-consistency coverage for the DeckSpec registry."""

from __future__ import annotations

from typing import cast

import pytest

from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.decks.spec import (
    DECK_SPECS,
    active_deck_cycle,
    coerce_known_deck,
    deck_spec,
)


def test_every_deck_id_has_exactly_one_spec() -> None:
    assert [s.deck_id for s in DECK_SPECS] == list(DeckId)
    assert active_deck_cycle() == (
        DeckId.MAIN,
        DeckId.FILES,
        DeckId.TOOLS,
        DeckId.FINAL,
    )
    for deck in DeckId:
        assert deck_spec(deck).deck_id is deck


def test_final_deck_spec_identity_and_cycle() -> None:
    spec = deck_spec(DeckId.FINAL)
    assert spec.name == "FINAL"
    assert spec.glyph == "⊛"
    assert spec.picker_key == "n"
    assert spec.count_noun == ("finalizer", "finalizers")
    assert spec.fallback_accent == "#FF87D7"
    assert active_deck_cycle() == (
        DeckId.MAIN,
        DeckId.FILES,
        DeckId.TOOLS,
        DeckId.FINAL,
    )


def test_picker_keys_unique_and_unreserved() -> None:
    keys = [s.picker_key for s in DECK_SPECS]
    assert all(len(k) == 1 and k.islower() for k in keys)
    assert len(set(keys)) == len(keys)
    assert not (set(keys) & {"j", "k", "q", "p"})


def test_derived_tables_match_specs() -> None:
    from sase.ace.tui.modals.deck_picker_modal import _DECK_CLASS
    from sase.ace.tui.widgets.decks.panel import _DECK_ACCENT_CLASS
    from sase.ace.tui.widgets.decks.panel_chrome import _FALLBACK_ACCENTS
    from sase.ace.tui.widgets.decks.titles import (
        DECK_BLURBS,
        DECK_COUNT_NOUNS,
        DECK_GLYPHS,
        DECK_NAMES,
        DECK_PICKER_KEYS,
    )

    for spec in DECK_SPECS:
        assert DECK_GLYPHS[spec.deck_id] == spec.glyph
        assert DECK_NAMES[spec.deck_id] == spec.name
        assert DECK_PICKER_KEYS[spec.deck_id] == spec.picker_key
        assert DECK_BLURBS[spec.deck_id] == spec.blurb
        assert DECK_COUNT_NOUNS[spec.deck_id] == spec.count_noun
        assert _FALLBACK_ACCENTS[spec.deck_id] == spec.fallback_accent
        assert _DECK_ACCENT_CLASS[spec.deck_id] == spec.accent_class
        assert _DECK_CLASS[spec.deck_id] == spec.picker_class
    assert set(DECK_GLYPHS) == set(DeckId)
    assert set(_FALLBACK_ACCENTS) == set(DeckId)
    assert set(_DECK_ACCENT_CLASS) == set(DeckId)
    assert set(_DECK_CLASS) == set(DeckId)


def test_unknown_deck_lookup_and_coercion() -> None:
    unknown = cast(DeckId, "telemetry")
    with pytest.raises(KeyError):
        deck_spec(unknown)
    assert coerce_known_deck(unknown, context="test") is DeckId.MAIN
    for deck in DeckId:
        assert coerce_known_deck(deck, context="test") is deck


def test_persistence_decodes_inactive_deck_to_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.models.agent_deck_persistence import _decode_panel
    from sase.ace.tui.widgets.decks import spec as spec_module

    monkeypatch.setattr(spec_module, "active_deck_cycle", lambda: (DeckId.MAIN,))
    assert _decode_panel({"deck": "tools"}).deck is DeckId.MAIN
    assert _decode_panel({"deck": "main"}).deck is DeckId.MAIN
