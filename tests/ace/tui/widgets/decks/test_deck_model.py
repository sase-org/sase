"""Pure model tests for deck-panel-core."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.decks.layout import toggle_zoom
from sase.ace.tui.widgets.decks.model import (
    DECK_CYCLE,
    DECK_VIEW_CHOICES,
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
    DeckView,
    DeckViewPolicies,
    cycle_card_id,
    cycle_deck_id,
    resolve_active_card,
    with_panel_deck,
    with_panel_view,
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
    assert (
        resolve_active_card(["summary", "context", "reply"], None, partial=False)
        == "context"
    )
    assert resolve_active_card(["summary"], None, partial=False) == "summary"
    assert resolve_active_card([], None, partial=False) is None


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


def test_deck_view_choices_palette_order() -> None:
    assert DECK_VIEW_CHOICES == (
        DeckView.AUTO,
        DeckView.SPREAD,
        DeckView.PAGE_CARDS,
        DeckView.PAGE_BLOCKS,
    )


def test_view_policies_for_deck() -> None:
    policies = DeckViewPolicies(main=DeckView.PAGE_BLOCKS, files=DeckView.SPREAD)
    assert policies.for_deck(DeckId.MAIN) is DeckView.PAGE_BLOCKS
    assert policies.for_deck(DeckId.FILES) is DeckView.SPREAD
    assert policies.for_deck(DeckId.TOOLS) is DeckView.AUTO


def test_view_policies_with_deck_rejects_invalid() -> None:
    policies = DeckViewPolicies()
    assert (
        policies.with_deck(DeckId.MAIN, DeckView.PAGE_BLOCKS).main
        is DeckView.PAGE_BLOCKS
    )
    assert policies.with_deck(DeckId.FILES, DeckView.SPREAD).files is DeckView.SPREAD
    with pytest.raises(ValueError):
        policies.with_deck(DeckId.TOOLS, DeckView.SPREAD)
    with pytest.raises(ValueError):
        policies.with_deck(DeckId.TOOLS, DeckView.AUTO)
    with pytest.raises(ValueError):
        policies.with_deck(DeckId.FILES, DeckView.PAGE_BLOCKS)


def test_replace_helpers_keep_views() -> None:
    state = DeckAreaState(
        panels=(
            DeckPanelState(
                deck=DeckId.MAIN,
                preferred_cards={DeckId.MAIN: "reply"},
                views=DeckViewPolicies(main=DeckView.SPREAD),
            ),
        ),
    )
    moved = with_panel_deck(state, 0, DeckId.FILES)
    assert moved.panels[0].views.main is DeckView.SPREAD
    assert moved.panels[0].deck is DeckId.FILES
    assert moved.panels[0].preferred_card == "reply"
    renamed = with_preferred_card(state, 0, "context")
    assert renamed.panels[0].views.main is DeckView.SPREAD
    assert renamed.panels[0].preferred_card == "context"


def test_with_preferred_card_scopes_to_panel_deck() -> None:
    state = DeckAreaState(
        panels=(DeckPanelState(deck=DeckId.FILES),),
    )
    updated = with_preferred_card(state, 0, "reply")
    assert updated.panels[0].preferred_card_for(DeckId.FILES) == "reply"
    assert updated.panels[0].preferred_card is None
    # An explicit deck stores under that deck even when the panel shows Main.
    main_state = DeckAreaState(
        panels=(DeckPanelState(deck=DeckId.MAIN),),
    )
    scoped = with_preferred_card(main_state, 0, "reply", DeckId.FILES)
    assert scoped.panels[0].preferred_card_for(DeckId.FILES) == "reply"
    assert scoped.panels[0].preferred_card is None
    # Clearing one deck keeps the other deck's sticky card.
    both = with_preferred_card(main_state, 0, "reply")
    both = with_preferred_card(both, 0, "notes", DeckId.FILES)
    cleared = with_preferred_card(both, 0, None)
    assert cleared.panels[0].preferred_card is None
    assert cleared.panels[0].preferred_card_for(DeckId.FILES) == "notes"


def test_with_panel_deck_keeps_every_deck_preference() -> None:
    state = DeckAreaState(
        panels=(
            DeckPanelState(
                deck=DeckId.MAIN,
                preferred_cards={DeckId.MAIN: "reply", DeckId.FILES: "notes"},
            ),
        ),
    )
    moved = with_panel_deck(state, 0, DeckId.FILES)
    assert moved.panels[0].preferred_card == "reply"
    assert moved.panels[0].preferred_card_for(DeckId.FILES) == "notes"


def test_with_panel_view_updates_zoom_snapshot() -> None:
    state = DeckAreaState(
        panels=(
            DeckPanelState(DeckId.MAIN),
            DeckPanelState(DeckId.FILES),
        ),
        focused=1,
        layout=DeckLayout.LEFT_RIGHT,
    )
    zoomed = toggle_zoom(state)
    updated = with_panel_view(zoomed, 1, DeckId.FILES, DeckView.SPREAD)
    assert updated.panels[1].views.files is DeckView.SPREAD
    assert updated.zoom_snapshot is not None
    assert updated.zoom_snapshot.panels[1].views.files is DeckView.SPREAD
    # The other panel is untouched in both states.
    assert updated.panels[0].views.files is DeckView.AUTO
    assert updated.zoom_snapshot.panels[0].views.files is DeckView.AUTO
    with pytest.raises(IndexError):
        with_panel_view(state, 5, DeckId.MAIN, DeckView.SPREAD)
    with pytest.raises(ValueError):
        with_panel_view(state, 0, DeckId.TOOLS, DeckView.SPREAD)
