"""Pure model tests for deck-panel-core."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.decks.model import (
    DECK_CYCLE,
    DeckAreaState,
    DeckId,
    DeckPanelState,
    cycle_card_id,
    cycle_deck_id,
    default_card_id,
    resolve_active_card,
    with_panel_deck,
    with_preferred_card,
)


def test_deck_cycle_order() -> None:
    assert DECK_CYCLE == (DeckId.MAIN, DeckId.FILES, DeckId.TOOLS)


def test_cycle_deck_id_wraps_both_directions() -> None:
    assert cycle_deck_id(DeckId.MAIN, 1) is DeckId.FILES
    assert cycle_deck_id(DeckId.FILES, 1) is DeckId.TOOLS
    assert cycle_deck_id(DeckId.TOOLS, 1) is DeckId.MAIN
    assert cycle_deck_id(DeckId.MAIN, -1) is DeckId.TOOLS
    assert cycle_deck_id(DeckId.TOOLS, -1) is DeckId.FILES


def test_cycle_card_id_wraps_both_directions() -> None:
    ids = ["context", "reply"]
    assert cycle_card_id(ids, "context", 1) == "reply"
    assert cycle_card_id(ids, "reply", 1) == "context"
    assert cycle_card_id(ids, "context", -1) == "reply"
    assert cycle_card_id(ids, "reply", -1) == "context"


def test_cycle_card_id_single_card_is_identity() -> None:
    assert cycle_card_id(["llm-calls"], "llm-calls", 1) == "llm-calls"
    assert cycle_card_id(["llm-calls"], "llm-calls", -1) == "llm-calls"


def test_cycle_card_id_empty_is_none() -> None:
    assert cycle_card_id([], None, 1) is None
    assert cycle_card_id([], "reply", -1) is None


def test_cycle_card_id_unknown_anchor_steps_from_default() -> None:
    ids = ["context", "reply"]
    assert cycle_card_id(ids, "gone", 1) == "reply"
    assert cycle_card_id(ids, "gone", -1) == "context"


def test_default_single_is_main() -> None:
    state = DeckAreaState()
    assert state.panels == (DeckPanelState(DeckId.MAIN),)
    assert state.focused == 0


def test_with_panel_deck_returns_new_state() -> None:
    state = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.MAIN)),
    )
    updated = with_panel_deck(state, 1, DeckId.FILES)
    assert updated.panels[1].deck is DeckId.FILES
    assert updated.panels[0].deck is DeckId.MAIN
    assert state.panels[1].deck is DeckId.MAIN


def test_with_panel_deck_out_of_range() -> None:
    state = DeckAreaState()
    with pytest.raises(IndexError):
        with_panel_deck(state, 5, DeckId.FILES)


def test_with_preferred_card() -> None:
    state = DeckAreaState()
    updated = with_preferred_card(state, 0, "reply")
    assert updated.panels[0].preferred_card == "reply"
    with pytest.raises(IndexError):
        with_preferred_card(state, 3, "reply")


def test_default_card_id_prefers_context() -> None:
    assert default_card_id(["summary", "context", "reply"]) == "context"
    assert default_card_id(["summary"]) == "summary"
    assert default_card_id([]) is None


def test_resolve_active_card() -> None:
    assert resolve_active_card(["context", "reply"], "reply", partial=False) == "reply"
    assert resolve_active_card(["context"], "reply", partial=False) == "context"
    # Partial without the preferred card keeps the tab strip with an empty body.
    assert resolve_active_card(["context"], "reply", partial=True) is None
    # Full paint without the preferred card falls back to the default.
    assert resolve_active_card(["context"], "reply", partial=False) == "context"
    # No preference falls back to the default.
    assert resolve_active_card(["summary"], None, partial=False) == "summary"
    assert resolve_active_card([], None, partial=False) is None
    # Partial with no preference still falls back (nothing to keep).
    assert resolve_active_card(["context"], None, partial=True) == "context"
