"""Pure layout transitions for deck-splits-focus."""

from __future__ import annotations

from sase.ace.tui.util.pane_grid import Axis, PaneGrid
from sase.ace.tui.widgets.decks.layout import (
    RATIO_STEPS,
    choose_new_panel,
    close_deck_panel,
    exit_zoom_keeping_panels,
    new_panel_for_deck,
    step_ratio,
    swap_deck_panel,
    toggle_focus,
    toggle_focus_reverse,
    toggle_split,
    toggle_zoom,
    turn_deck_layout,
)
from sase.ace.tui.widgets.decks.model import (
    DeckAreaState,
    DeckId,
    DeckLayout,
    DeckPanelState,
)


def _single(deck: DeckId = DeckId.MAIN) -> DeckAreaState:
    return DeckAreaState(panels={0: DeckPanelState(deck)})


def _split(
    deck0: DeckId,
    deck1: DeckId,
    *,
    focused: int = 1,
    layout: DeckLayout = DeckLayout.TOP_BOTTOM,
    ratio: int = 50,
) -> DeckAreaState:
    axis = Axis.COLS if layout is DeckLayout.LEFT_RIGHT else Axis.ROWS
    other = 1 - focused
    return DeckAreaState(
        grid=PaneGrid(
            panes=(0, 1),
            focused=focused,
            axis=axis,
            ratio=ratio,
            recent=(focused, other),
        ),
        panels={0: DeckPanelState(deck0), 1: DeckPanelState(deck1)},
    )


def test_single_backslash_opens_top_bottom() -> None:
    state = _single(DeckId.MAIN)
    new_panel = DeckPanelState(DeckId.FILES)
    updated = toggle_split(state, DeckLayout.TOP_BOTTOM, new_panel)
    assert updated.layout is DeckLayout.TOP_BOTTOM
    assert updated.panels == {0: DeckPanelState(DeckId.MAIN), 1: new_panel}
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


def test_top_bottom_backslash_unsplits_keeping_focused() -> None:
    state = _split(DeckId.MAIN, DeckId.FILES, focused=1, ratio=30)
    updated = toggle_split(state, DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.TOOLS))
    assert updated.layout is DeckLayout.SINGLE
    assert updated.panels == {1: DeckPanelState(DeckId.FILES)}
    assert updated.focused == 1
    assert updated.ratio == 50


def test_top_bottom_backslash_unsplits_keeping_first_when_focused() -> None:
    state = _split(DeckId.MAIN, DeckId.FILES, focused=0, ratio=30)
    updated = toggle_split(state, DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.TOOLS))
    assert updated.panels == {0: DeckPanelState(DeckId.MAIN)}
    assert updated.focused == 0
    assert updated.layout is DeckLayout.SINGLE


def test_left_right_pipe_unsplits_keeping_focused() -> None:
    state = _split(
        DeckId.FILES, DeckId.TOOLS, focused=1, layout=DeckLayout.LEFT_RIGHT, ratio=70
    )
    updated = toggle_split(state, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.MAIN))
    assert updated.panels == {1: DeckPanelState(DeckId.TOOLS)}
    assert updated.focused == 1
    assert updated.layout is DeckLayout.SINGLE


def test_other_key_nests_third_panel_keeping_outer_shape() -> None:
    state = _split(DeckId.MAIN, DeckId.FILES, focused=1, ratio=30)
    state = DeckAreaState(
        grid=state.grid,
        panels={
            0: DeckPanelState(deck=DeckId.MAIN, preferred_cards={DeckId.MAIN: "reply"}),
            1: DeckPanelState(DeckId.FILES),
        },
    )
    nested = toggle_split(state, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.TOOLS))
    assert len(nested.grid.panes) == 3
    assert nested.layout is DeckLayout.TOP_BOTTOM
    assert nested.focused == 2
    assert nested.grid.ratio == 30
    assert nested.panels[2] == DeckPanelState(DeckId.TOOLS)
    assert nested.panels[0] == state.panels[0]
    assert nested.panels[1] == state.panels[1]


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


def test_final_taken_only_on_positive_content() -> None:
    content: dict[DeckId, bool | None] = {
        DeckId.MAIN: True,
        DeckId.FILES: False,
        DeckId.TOOLS: False,
        DeckId.FINAL: True,
    }
    chosen = choose_new_panel(
        DeckId.MAIN, "context", {DeckId.MAIN}, content, ("context", "reply")
    )
    assert chosen.deck is DeckId.FINAL


def test_final_unknown_or_empty_falls_back_to_duplicate() -> None:
    for final_content in (None, False):
        content: dict[DeckId, bool | None] = {
            DeckId.MAIN: True,
            DeckId.FILES: False,
            DeckId.TOOLS: False,
            DeckId.FINAL: final_content,
        }
        chosen = choose_new_panel(
            DeckId.MAIN, "context", {DeckId.MAIN}, content, ("context", "reply")
        )
        assert chosen.deck is DeckId.MAIN
        assert chosen.preferred_card == "reply"


def test_ratio_steps_from_each_focused_side_and_clamp() -> None:
    top = _split(DeckId.MAIN, DeckId.FILES, focused=0)
    assert step_ratio(top, True).ratio == 70
    assert step_ratio(top, False).ratio == 30
    assert step_ratio(step_ratio(top, True), True).ratio == 70
    bottom = _split(DeckId.MAIN, DeckId.FILES, focused=1)
    assert step_ratio(bottom, True).ratio == 30
    assert step_ratio(bottom, False).ratio == 70
    assert step_ratio(step_ratio(bottom, False), False).ratio == 70


def test_toggle_focus_single_is_noop() -> None:
    state = _single()
    assert toggle_focus(state) is state


def test_toggle_focus_flips_in_split() -> None:
    state = _split(DeckId.MAIN, DeckId.FILES, focused=0, layout=DeckLayout.LEFT_RIGHT)
    assert toggle_focus(state).focused == 1
    assert toggle_focus(toggle_focus(state)).focused == 0


def test_unsplit_keeps_focused_panel_involution() -> None:
    single = _single(DeckId.MAIN)
    opened = toggle_split(single, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.FILES))
    assert opened.focused == 1
    closed = toggle_split(opened, DeckLayout.LEFT_RIGHT, DeckPanelState(DeckId.TOOLS))
    assert closed == DeckAreaState(
        grid=PaneGrid(panes=(1,), focused=1, recent=(1,)),
        panels={1: DeckPanelState(DeckId.FILES)},
    )


def test_ratio_steps_constant() -> None:
    assert RATIO_STEPS == (30, 50, 70)


def test_toggle_split_focus_new_false_keeps_focus_on_first_panel() -> None:
    state = _single(DeckId.MAIN)
    new_panel = DeckPanelState(DeckId.FILES)
    updated = toggle_split(state, DeckLayout.TOP_BOTTOM, new_panel, focus_new=False)
    assert updated.layout is DeckLayout.TOP_BOTTOM
    assert updated.panels == {0: DeckPanelState(DeckId.MAIN), 1: new_panel}
    assert updated.focused == 0
    assert updated.ratio == 50
    # The default still moves focus into the new panel.
    assert toggle_split(state, DeckLayout.TOP_BOTTOM, new_panel).focused == 1


def test_toggle_split_focus_new_ignored_by_unsplit_and_nest() -> None:
    split = _split(DeckId.MAIN, DeckId.FILES, focused=1, ratio=30)
    other = DeckPanelState(DeckId.TOOLS)
    for flag in (True, False):
        nested = toggle_split(split, DeckLayout.LEFT_RIGHT, other, focus_new=flag)
        assert len(nested.grid.panes) == 3
        assert nested.grid.ratio == 30
        if flag:
            assert nested.focused == 2
        else:
            assert nested.focused == 1
        unsplit = toggle_split(split, DeckLayout.TOP_BOTTOM, other, focus_new=flag)
        assert unsplit.layout is DeckLayout.SINGLE
        assert unsplit.focused == 1
        assert unsplit.panels == {1: DeckPanelState(DeckId.FILES)}


def test_split_key_while_zoomed_only_restores() -> None:
    split = _split(DeckId.MAIN, DeckId.FILES, focused=1, layout=DeckLayout.LEFT_RIGHT)
    zoomed = toggle_zoom(split)
    assert zoomed.focused == 1
    restored = toggle_split(zoomed, DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.TOOLS))
    assert restored == split
    # Same-key press restores too: no split opens and nothing is lost.
    zoomed_single = toggle_zoom(_single(DeckId.MAIN))
    assert toggle_split(
        zoomed_single, DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.FILES)
    ) == _single(DeckId.MAIN)


def test_new_panel_for_deck_duplicate_main_takes_next_card_with_wrap() -> None:
    cards = ("context", "prompt", "reply")
    assert new_panel_for_deck(
        DeckId.MAIN, DeckId.MAIN, "context", cards
    ) == DeckPanelState(deck=DeckId.MAIN, preferred_cards={DeckId.MAIN: "prompt"})
    assert new_panel_for_deck(
        DeckId.MAIN, DeckId.MAIN, "reply", cards
    ) == DeckPanelState(deck=DeckId.MAIN, preferred_cards={DeckId.MAIN: "context"})


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
    import dataclasses

    split = _split(
        DeckId.MAIN, DeckId.FILES, focused=1, layout=DeckLayout.LEFT_RIGHT, ratio=70
    )
    zoomed = toggle_zoom(split)
    assert zoomed.nodes_collapsed is split.nodes_collapsed
    # A deck changed while zoomed (Ctrl+N) must survive ending the zoom.
    zoomed = dataclasses.replace(
        zoomed,
        panels={0: DeckPanelState(DeckId.MAIN), 1: DeckPanelState(DeckId.TOOLS)},
    )

    restored = exit_zoom_keeping_panels(zoomed)

    assert restored.zoom_snapshot is None
    assert restored.layout is DeckLayout.LEFT_RIGHT
    assert restored.ratio == 70
    assert restored.nodes_collapsed is False
    assert restored.panels == {
        0: DeckPanelState(DeckId.MAIN),
        1: DeckPanelState(DeckId.TOOLS),
    }
    assert restored.focused == 1


def test_exit_zoom_keeping_panels_unzoomed_state_is_unchanged() -> None:
    state = _single(DeckId.FILES)
    assert exit_zoom_keeping_panels(state) is state


def test_toggle_focus_reverse_flips_in_split() -> None:
    state = _split(DeckId.MAIN, DeckId.FILES, focused=0, layout=DeckLayout.LEFT_RIGHT)
    assert toggle_focus_reverse(state).focused == 1
    assert toggle_focus_reverse(toggle_focus_reverse(state)).focused == 0


def test_toggle_focus_reverse_single_is_noop() -> None:
    state = _single()
    assert toggle_focus_reverse(state) is state


def test_swap_deck_panel_permutes_panes_and_keeps_sessions() -> None:
    state = _split(DeckId.MAIN, DeckId.FILES, focused=0)
    swapped = swap_deck_panel(state, +1)
    assert swapped.grid.panes == (1, 0)
    assert swapped.grid.focused == 0
    assert swapped.panels == {
        0: DeckPanelState(DeckId.MAIN),
        1: DeckPanelState(DeckId.FILES),
    }
    assert swapped.ratio == state.ratio
    assert swapped.layout is state.layout


def test_swap_deck_panel_single_is_noop() -> None:
    state = _single()
    assert swap_deck_panel(state, +1) is state
    assert swap_deck_panel(state, -1) is state


def test_close_deck_panel_removes_focused_pane() -> None:
    focused_last = _split(DeckId.MAIN, DeckId.FILES, focused=1, ratio=30)
    closed = close_deck_panel(focused_last)
    assert closed.layout is DeckLayout.SINGLE
    assert closed.panels == {0: DeckPanelState(DeckId.MAIN)}
    assert closed.focused == 0


def test_close_deck_panel_removes_first_pane_when_focused() -> None:
    focused_first = _split(DeckId.MAIN, DeckId.FILES, focused=0)
    closed = close_deck_panel(focused_first)
    assert closed.layout is DeckLayout.SINGLE
    assert closed.panels == {1: DeckPanelState(DeckId.FILES)}
    assert closed.focused == 1


def test_close_deck_panel_single_is_noop() -> None:
    state = _single()
    assert close_deck_panel(state) is state


def test_close_deck_panel_is_inverse_of_split() -> None:
    single = _single(DeckId.MAIN)
    opened = toggle_split(single, DeckLayout.TOP_BOTTOM, DeckPanelState(DeckId.FILES))
    assert opened.focused == 1
    assert close_deck_panel(opened).grid.panes == (0,)
    refocused = toggle_focus(opened)
    assert refocused.focused == 0
    assert close_deck_panel(refocused).grid.panes == (1,)


def test_turn_deck_layout_transposes_two_pane_split() -> None:
    state = _split(
        DeckId.MAIN, DeckId.FILES, focused=1, layout=DeckLayout.TOP_BOTTOM, ratio=70
    )
    turned = turn_deck_layout(state)
    assert turned.layout is DeckLayout.LEFT_RIGHT
    assert turned.focused == 1
    assert turned.ratio == 70
    assert turned.panels == state.panels
    assert turn_deck_layout(turned).layout is DeckLayout.TOP_BOTTOM


def test_turn_deck_layout_single_is_noop() -> None:
    state = _single()
    assert turn_deck_layout(state) is state


def test_pane_keys_disabled_while_zoomed() -> None:
    split = _split(DeckId.MAIN, DeckId.FILES, focused=1, layout=DeckLayout.LEFT_RIGHT)
    zoomed = toggle_zoom(split)
    assert toggle_focus(zoomed) is zoomed
    assert toggle_focus_reverse(zoomed) is zoomed
    assert swap_deck_panel(zoomed, +1) is zoomed
    assert close_deck_panel(zoomed) is zoomed
    assert turn_deck_layout(zoomed) is zoomed
    assert step_ratio(zoomed, True) is zoomed
