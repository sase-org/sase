"""Pure layout transitions for deck-splits-focus."""

from __future__ import annotations

from sase.ace.tui.widgets.decks.layout import (
    RATIO_STEPS,
    choose_new_panel,
    exit_zoom_keeping_panels,
    new_panel_for_deck,
    step_ratio,
    toggle_focus,
    toggle_split,
    toggle_zoom,
)
from sase.ace.tui.widgets.decks.model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
)


def _single(deck: DeckId = DeckId.MAIN) -> DeckAreaState:
    return DeckAreaState(panels=(DeckPanelState(deck),), focused=0)


def test_single_backslash_opens_top_bottom() -> None:
    state = _single(DeckId.MAIN)
    new_panel = DeckPanelState(DeckId.FILES)
    updated = toggle_split(state, DeckLayout.TOP_BOTTOM, new_panel)
    assert updated.layout is DeckLayout.TOP_BOTTOM
    assert updated.panels == (DeckPanelState(DeckId.MAIN), new_panel)
    assert updated.focused == 1
    assert updated.ratio == 50


def test_single_pipe_opens_left_right() -> None:
    state = _single(DeckId.MAIN)
    new_panel = DeckPanelState(DeckId.FILES)
    updated = toggle_split(state, DeckLayout.LEFT_RIGHT, new_panel)
    assert updated.layout is DeckLayout.LEFT_RIGHT
    assert updated.panels[1] == new_panel
    assert updated.focused == 1
    assert updated.ratio == 50


def test_top_bottom_backslash_unsplits_to_first() -> None:
    state = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.FILES)),
        focused=1,
        layout=DeckLayout.TOP_BOTTOM,
        ratio=30,
    )
    updated = toggle_split(state, DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.TOOLS))
    assert updated.layout is DeckLayout.SINGLE
    assert updated.panels == (DeckPanelState(DeckId.MAIN),)
    assert updated.focused == 0
    assert updated.ratio == 50


def test_left_right_pipe_unsplits_keeps_first() -> None:
    state = DeckAreaState(
        panels=(DeckPanelState(DeckId.FILES), DeckPanelState(DeckId.TOOLS)),
        focused=1,
        layout=DeckLayout.LEFT_RIGHT,
        ratio=70,
    )
    updated = toggle_split(state, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.MAIN))
    assert updated.panels == (DeckPanelState(DeckId.FILES),)
    assert updated.focused == 0
    assert updated.layout is DeckLayout.SINGLE


def test_rotate_keeps_everything_but_layout() -> None:
    state = DeckAreaState(
        panels=(
            DeckPanelState(DeckId.MAIN, "reply"),
            DeckPanelState(DeckId.FILES),
        ),
        focused=1,
        layout=DeckLayout.TOP_BOTTOM,
        ratio=30,
    )
    rotated = toggle_split(state, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.TOOLS))
    assert rotated.layout is DeckLayout.LEFT_RIGHT
    assert rotated.panels == state.panels
    assert rotated.focused == 1
    assert rotated.ratio == 30
    back = toggle_split(rotated, DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.MAIN))
    assert back.layout is DeckLayout.TOP_BOTTOM
    assert back.panels == state.panels


def test_new_panel_skips_shown_with_content() -> None:
    chosen = choose_new_panel(
        DeckId.MAIN,
        "context",
        {DeckId.MAIN},
        {
            DeckId.MAIN: True,
            DeckId.FILES: True,
            DeckId.TOOLS: True,
        },
        ("context", "reply"),
    )
    assert chosen.deck is DeckId.FILES


def test_no_files_no_tools_gives_context_reply() -> None:
    chosen = choose_new_panel(
        DeckId.MAIN,
        "context",
        {DeckId.MAIN},
        {
            DeckId.MAIN: True,
            DeckId.FILES: False,
            DeckId.TOOLS: False,
        },
        ("context", "reply"),
    )
    assert chosen.deck is DeckId.MAIN
    assert chosen.preferred_card == "reply"


def test_unknown_availability_counts_as_content() -> None:
    chosen = choose_new_panel(
        DeckId.MAIN,
        "context",
        {DeckId.MAIN},
        {
            DeckId.MAIN: True,
            DeckId.FILES: None,
            DeckId.TOOLS: False,
        },
        ("context", "reply"),
    )
    assert chosen.deck is DeckId.FILES


def test_duplicate_main_opens_on_next_card_with_wrap() -> None:
    chosen = choose_new_panel(
        DeckId.MAIN,
        "reply",
        {DeckId.MAIN, DeckId.FILES, DeckId.TOOLS},
        {
            DeckId.MAIN: True,
            DeckId.FILES: True,
            DeckId.TOOLS: True,
        },
        ("context", "reply"),
    )
    assert chosen.deck is DeckId.MAIN
    assert chosen.preferred_card == "context"


def test_duplicate_files_has_no_preferred_card() -> None:
    chosen = choose_new_panel(
        DeckId.FILES,
        None,
        {DeckId.MAIN, DeckId.FILES, DeckId.TOOLS},
        {
            DeckId.MAIN: True,
            DeckId.FILES: True,
            DeckId.TOOLS: True,
        },
        (),
    )
    assert chosen.deck is DeckId.FILES
    assert chosen.preferred_card is None


def test_ratio_steps_from_each_focused_side_and_clamp() -> None:
    top = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.FILES)),
        focused=0,
        layout=DeckLayout.TOP_BOTTOM,
        ratio=50,
    )
    assert step_ratio(top, True).ratio == 70
    assert step_ratio(top, False).ratio == 30
    assert step_ratio(step_ratio(top, True), True).ratio == 70
    bottom = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.FILES)),
        focused=1,
        layout=DeckLayout.TOP_BOTTOM,
        ratio=50,
    )
    assert step_ratio(bottom, True).ratio == 30
    assert step_ratio(bottom, False).ratio == 70
    assert step_ratio(step_ratio(bottom, False), False).ratio == 70


def test_toggle_focus_single_is_noop() -> None:
    state = _single()
    assert toggle_focus(state) is state


def test_toggle_focus_flips_in_split() -> None:
    state = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.FILES)),
        focused=0,
        layout=DeckLayout.LEFT_RIGHT,
        ratio=50,
    )
    assert toggle_focus(state).focused == 1
    assert toggle_focus(toggle_focus(state)).focused == 0


def test_unsplit_keeps_panel_zero_involution() -> None:
    single = _single(DeckId.MAIN)
    opened = toggle_split(single, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.FILES))
    assert opened.focused == 1
    closed = toggle_split(opened, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.TOOLS))
    assert closed == DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN),),
        focused=0,
        layout=DeckLayout.SINGLE,
        ratio=50,
    )


def test_ratio_steps_constant() -> None:
    assert RATIO_STEPS == (30, 50, 70)


def test_toggle_split_focus_new_false_keeps_focus_on_first_panel() -> None:
    state = _single(DeckId.MAIN)
    new_panel = DeckPanelState(DeckId.FILES)
    updated = toggle_split(state, DeckLayout.TOP_BOTTOM, new_panel, focus_new=False)
    assert updated.layout is DeckLayout.TOP_BOTTOM
    assert updated.panels == (DeckPanelState(DeckId.MAIN), new_panel)
    assert updated.focused == 0
    assert updated.ratio == 50
    # The default still moves focus into the new panel.
    assert toggle_split(state, DeckLayout.TOP_BOTTOM, new_panel).focused == 1


def test_toggle_split_focus_new_ignored_by_unsplit_and_rotate() -> None:
    split = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.FILES)),
        focused=1,
        layout=DeckLayout.TOP_BOTTOM,
        ratio=30,
    )
    other = DeckPanelState(DeckId.TOOLS)
    for flag in (True, False):
        rotated = toggle_split(split, DeckLayout.LEFT_RIGHT, other, focus_new=flag)
        assert rotated.layout is DeckLayout.LEFT_RIGHT
        assert rotated.focused == 1
        assert rotated.ratio == 30
        unsplit = toggle_split(split, DeckLayout.TOP_BOTTOM, other, focus_new=flag)
        assert unsplit.layout is DeckLayout.SINGLE
        assert unsplit.focused == 0


def test_new_panel_for_deck_duplicate_main_takes_next_card_with_wrap() -> None:
    cards = ("context", "prompt", "reply")
    assert new_panel_for_deck(
        DeckId.MAIN, DeckId.MAIN, "context", cards
    ) == DeckPanelState(DeckId.MAIN, "prompt")
    assert new_panel_for_deck(
        DeckId.MAIN, DeckId.MAIN, "reply", cards
    ) == DeckPanelState(DeckId.MAIN, "context")


def test_new_panel_for_deck_non_duplicate_has_no_preferred_card() -> None:
    cards = ("context", "reply")
    assert new_panel_for_deck(
        DeckId.FILES, DeckId.MAIN, "context", cards
    ) == DeckPanelState(DeckId.FILES)
    assert new_panel_for_deck(DeckId.MAIN, DeckId.FILES, None, cards) == DeckPanelState(
        DeckId.MAIN
    )
    assert new_panel_for_deck(
        DeckId.FILES, DeckId.FILES, None, cards
    ) == DeckPanelState(DeckId.FILES)


def test_exit_zoom_keeping_panels_restores_layout_but_keeps_current_panels() -> None:
    split = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.FILES)),
        focused=1,
        layout=DeckLayout.LEFT_RIGHT,
        ratio=70,
        nodes_collapsed=False,
    )
    zoomed = toggle_zoom(split)
    assert zoomed.nodes_collapsed is True
    # A deck changed while zoomed (Ctrl+N) must survive ending the zoom.
    zoomed = DeckAreaState(
        panels=(DeckPanelState(DeckId.MAIN), DeckPanelState(DeckId.TOOLS)),
        focused=zoomed.focused,
        layout=zoomed.layout,
        ratio=zoomed.ratio,
        nodes_collapsed=zoomed.nodes_collapsed,
        zoom_snapshot=zoomed.zoom_snapshot,
    )

    restored = exit_zoom_keeping_panels(zoomed)

    assert restored.zoom_snapshot is None
    assert restored.layout is DeckLayout.LEFT_RIGHT
    assert restored.ratio == 70
    assert restored.nodes_collapsed is False
    assert restored.panels == (
        DeckPanelState(DeckId.MAIN),
        DeckPanelState(DeckId.TOOLS),
    )
    assert restored.focused == 1


def test_exit_zoom_keeping_panels_unzoomed_state_is_unchanged() -> None:
    state = _single(DeckId.FILES)
    assert exit_zoom_keeping_panels(state) is state
