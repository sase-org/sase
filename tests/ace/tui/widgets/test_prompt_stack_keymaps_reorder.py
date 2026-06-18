"""Prompt-stack keymap tests for pane reorder and retired reorder chords.

Covers pane reorder on ``gJ`` (lower/later) / ``gK`` (higher/earlier), which is
NORMAL-mode-only. Normal-mode ``Up``/``Down`` move the cursor instead of
reordering panes, and retired structural reorder chords no longer fire.
"""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._prompt_stack_keymap_helpers import PromptStackKeymapApp


# --- reorder (NORMAL-mode gK / gJ) -----------------------------------------


async def test_gk_moves_active_pane_higher() -> None:
    """``gK`` moves the active pane higher/earlier."""
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "K")  # move "third" higher/earlier
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["first", "third", "second"]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "third"
        # The moved pane stays active and in normal mode for repeated reorders.
        assert bar.active_text_area()._vim_mode == "normal"


async def test_ctrl_gk_moves_active_pane_higher_from_insert_and_keeps_insert() -> None:
    """``Ctrl+G K`` reorders without requiring an Esc/i round trip."""
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("ctrl+g", "K")  # move "third" higher/earlier
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["first", "third", "second"]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "third"
        assert bar.active_text_area()._vim_mode == "insert"


async def test_gj_moves_active_pane_lower() -> None:
    """``gJ`` moves the active pane lower/later."""
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "k")  # focus "second" (index 1)
        await pilot.pause()
        await pilot.press("g", "J")  # move "second" lower/later
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["first", "third", "second"]
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "second"


async def test_reorder_preserves_live_edits() -> None:
    app = PromptStackKeymapApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Edit the active (bottom) pane before reordering.
        await pilot.press("!")
        await pilot.pause()
        assert bar.active_text() == "second!"

        await pilot.press("escape")
        await pilot.press("g", "K")  # move "second!" higher/earlier
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["second!", "first"]


async def test_g_prefix_reorder_is_normal_mode_only() -> None:
    """``gJ``/``gK`` are NORMAL-mode-only: in insert mode they never reorder."""
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Default mode is insert; the bottom pane is active.
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("g", "J")
        await pilot.press("g", "K")
        await pilot.pause()
        await pilot.pause()

        # The stack order and selection are untouched (insert-mode g/J/K are
        # literal text, not pane reorder).
        assert bar.all_prompt_texts() == ["first", "second", "thirdgJgK"]
        assert bar._stack.selected_index == 2
        assert bar.active_text_area()._vim_mode == "insert"


async def test_gk_on_top_pane_wraps_to_bottom() -> None:
    """``gK`` on the top pane cycles it to the bottom, still active."""
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "k")  # focus "second"
        await pilot.press("g", "k")  # focus "first" (top pane, index 0)
        await pilot.pause()
        assert bar._stack.selected_index == 0

        await pilot.press("g", "K")  # move "first" up past the top -> bottom
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["second", "third", "first"]
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "first"
        assert bar.active_text_area()._vim_mode == "normal"


async def test_gj_on_bottom_pane_wraps_to_top() -> None:
    """``gJ`` on the bottom pane cycles it to the top, still active."""
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        assert bar._stack.selected_index == 2  # bottom pane "third"

        await pilot.press("g", "J")  # move "third" down past the bottom -> top
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["third", "first", "second"]
        assert bar._stack.selected_index == 0
        assert bar.active_text() == "third"
        assert bar.active_text_area()._vim_mode == "normal"


async def test_ctrl_shift_h_l_no_longer_reorder_panes() -> None:
    """Retired ``Ctrl+Shift+H``/``Ctrl+Shift+L`` no longer reorder panes."""
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")

        await pilot.press("ctrl+shift+h")  # used to move the active pane up
        await pilot.press("ctrl+shift+l")  # used to move the active pane down
        await pilot.pause()
        await pilot.pause()

        # Reorder moved to gJ/gK, so the old chords leave the stack intact.
        assert bar.all_prompt_texts() == ["first", "second", "third"]
        assert bar._stack.selected_index == 2


async def test_single_pane_up_down_keep_cursor_movement() -> None:
    """A single pane has nothing to reorder, so arrows move the cursor."""
    app = PromptStackKeymapApp("alpha\nbeta\ngamma")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (2, 0)

        await pilot.press("up")
        await pilot.pause()
        assert text_area.cursor_location[0] == 1

        await pilot.press("down")
        await pilot.pause()
        assert text_area.cursor_location[0] == 2

        # Still a single pane: nothing was reordered.
        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["alpha\nbeta\ngamma"]


async def test_multi_pane_normal_arrows_move_cursor_not_panes() -> None:
    """Normal-mode ``Up``/``Down`` move the cursor; reorder moved to gJ/gK.

    Removing the old normal-mode arrow reorder special case means a multi-pane
    stack regains ordinary TextArea cursor movement on the arrows.
    """
    app = PromptStackKeymapApp("first\n---\nalpha\nbeta\ngamma")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()  # bottom pane "alpha\nbeta\ngamma"
        assert bar._stack.selected_index == 1
        await pilot.press("escape")
        text_area.cursor_location = (2, 0)

        await pilot.press("up")
        await pilot.pause()
        assert text_area.cursor_location[0] == 1

        await pilot.press("down")
        await pilot.pause()
        assert text_area.cursor_location[0] == 2

        # The arrows moved the cursor inside the active pane; the stack order and
        # selection are untouched (reorder moved to gJ/gK).
        assert bar.all_prompt_texts() == ["first", "alpha\nbeta\ngamma"]
        assert bar._stack.selected_index == 1


async def test_comma_is_inert_now_that_stack_keymaps_moved_to_g_prefix() -> None:
    """Bare ``,`` is a prompt-local no-op; the ``g`` prefix owns stack stash/nav.

    The retired comma leader must swallow a lone ``,`` *without* opening a
    leader, stashing, or mutating the stack, while the migrated ``gs`` stash
    still dispatches through the ``g`` prefix.
    """
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        assert bar._stack.selected_index == 2

        # A lone ``,`` (no prior f/t char-search) is a swallowed no-op: neither
        # the stack order nor the focused pane changes, and nothing is stashed.
        await pilot.press("comma")
        await pilot.press("comma")
        await pilot.pause()
        assert bar.all_prompt_texts() == ["first", "second", "third"]
        assert bar._stack.selected_index == 2

        # The migrated ``gs`` stash still dispatches: it drops the active bottom
        # pane, proving the stash action moved cleanly onto the ``g`` prefix.
        await pilot.press("g", "s")
        await pilot.pause()
        await pilot.pause()
        assert bar.all_prompt_texts() == ["first", "second"]
