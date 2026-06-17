"""Widget-level tests for the prompt-stack keymaps.

Covers the multi-agent prompt stack keymaps: pane focus navigation lives on the
NORMAL-mode ``K``/``J`` keys and pane reorder on NORMAL-mode ``Up``/``Down``
(both NORMAL-mode-only); ``Ctrl+-`` adds a new bottom pane; a typed ``---``
separator line is inert (panes are created only through ``Ctrl+-``); the prompt
stash/structural keymaps migrated to the ``g`` prefix, so ``,`` is now a
prompt-local no-op that still defers to vim's reverse char-search repeat; and
the retired structural chords (``Ctrl+H``/``Ctrl+L`` focus,
``Ctrl+Shift+H``/``Ctrl+Shift+L`` reorder, ``J`` line join) no longer fire.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _PromptBarApp(App[None]):
    """Minimal app that hosts a single prompt input bar."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )


# --- pane focus navigation (NORMAL-mode K / J) -----------------------------


async def test_k_focuses_previous_pane_from_normal() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2

        await pilot.press("escape")  # active (bottom) pane -> normal mode
        await pilot.press("K")  # focus the pane above
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"
        assert app.focused is bar.active_text_area()
        # Focus navigation keeps the target pane in normal mode.
        assert bar.active_text_area()._vim_mode == "normal"


async def test_k_then_j_round_trips_focus() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("K")  # 2 -> 1
        await pilot.press("K")  # 1 -> 0
        await pilot.pause()
        assert bar._stack.selected_index == 0
        assert bar.active_text() == "first"

        await pilot.press("J")  # 0 -> 1
        await pilot.pause()
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"


async def test_k_cycles_from_top_to_bottom() -> None:
    """``K`` from the top pane wraps focus around to the bottom pane."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("K")  # 2 -> 1
        await pilot.press("K")  # 1 -> 0 (top pane)
        await pilot.pause()
        assert bar._stack.selected_index == 0

        await pilot.press("K")  # 0 -> 2 (wraps to the bottom pane)
        await pilot.pause()
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "third"
        # Cycling preserves normal mode.
        assert bar.active_text_area()._vim_mode == "normal"


async def test_j_focuses_next_pane_and_cycles_at_bottom_edge() -> None:
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("K")  # 1 -> 0 (focus the top pane)
        await pilot.pause()
        assert bar._stack.selected_index == 0

        await pilot.press("J")  # 0 -> 1 (focus the bottom pane)
        await pilot.pause()
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"

        # From the bottom pane J wraps around to the top pane.
        await pilot.press("J")  # 1 -> 0
        await pilot.pause()
        assert bar._stack.selected_index == 0
        assert bar.active_text() == "first"


async def test_kj_do_not_focus_panes_in_insert_mode() -> None:
    """``K``/``J`` are NORMAL-mode-only: in insert mode they type literally."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Default mode is insert; the bottom pane is active.
        assert bar.active_text_area()._vim_mode == "insert"
        assert bar._stack.selected_index == 2

        await pilot.press("K")
        await pilot.press("J")
        await pilot.pause()

        # Focus never moved; the keys were inserted as ordinary characters.
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "thirdKJ"


async def test_ctrl_h_l_no_longer_focus_panes() -> None:
    """Retired ``Ctrl+H``/``Ctrl+L`` no longer move pane focus."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        assert bar._stack.selected_index == 2

        await pilot.press("ctrl+h")  # used to focus the pane above
        await pilot.press("ctrl+l")  # used to focus the pane below
        await pilot.pause()

        # Focus navigation moved to K/J, so the old chords are inert.
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "third"


async def test_ctrl_l_does_not_focus_pane_when_consumed_by_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insert-mode ``Ctrl+L`` still accepts a soft completion and never focuses.

    Pane focus moved to the NORMAL-mode ``K``/``J`` keys, so ``Ctrl+L`` has no
    pane-focus fallback anymore -- it only accepts a soft completion (and
    otherwise falls through to the app-level ``dismiss_toasts`` binding).
    """
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        assert bar._stack.selected_index == 1

        # Force the completion branch to claim Ctrl+L for this keypress.
        monkeypatch.setattr(text_area, "_accept_or_build_soft_completion", lambda: True)

        await pilot.press("ctrl+l")
        await pilot.pause()

        # Completion consumed the key; focus stayed on the bottom pane.
        assert bar._stack.selected_index == 1
        assert app.focused is text_area


# --- reorder (NORMAL-mode Up / Down) ---------------------------------------


async def test_up_moves_active_pane_higher() -> None:
    """``Up`` moves the active pane higher/earlier (old ``Ctrl+Shift+H``)."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("up")  # move "third" higher/earlier
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["first", "third", "second"]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "third"
        # The moved pane stays active and in normal mode for repeated reorders.
        assert bar.active_text_area()._vim_mode == "normal"


async def test_down_moves_active_pane_lower() -> None:
    """``Down`` moves the active pane lower/later (old ``Ctrl+Shift+L``)."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("K")  # focus "second" (index 1)
        await pilot.pause()
        await pilot.press("down")  # move "second" lower/later
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["first", "third", "second"]
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "second"


async def test_reorder_preserves_live_edits() -> None:
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Edit the active (bottom) pane before reordering.
        await pilot.press("!")
        await pilot.pause()
        assert bar.active_text() == "second!"

        await pilot.press("escape")
        await pilot.press("up")  # move "second!" higher/earlier
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["second!", "first"]


async def test_up_down_do_not_reorder_in_insert_mode() -> None:
    """``Up``/``Down`` are NORMAL-mode-only: in insert mode they never reorder."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Default mode is insert; the bottom pane is active.
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("up")
        await pilot.press("down")
        await pilot.pause()
        await pilot.pause()

        # The stack order and selection are untouched (insert-mode arrows are
        # cursor / completion navigation, not pane reorder).
        assert bar.all_prompt_texts() == ["first", "second", "third"]
        assert bar._stack.selected_index == 2
        assert bar.active_text_area()._vim_mode == "insert"


async def test_up_on_top_pane_wraps_to_bottom() -> None:
    """``Up`` on the top pane cycles it to the bottom, still active."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("K")  # focus "second"
        await pilot.press("K")  # focus "first" (top pane, index 0)
        await pilot.pause()
        assert bar._stack.selected_index == 0

        await pilot.press("up")  # move "first" up past the top -> bottom
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["second", "third", "first"]
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "first"
        assert bar.active_text_area()._vim_mode == "normal"


async def test_down_on_bottom_pane_wraps_to_top() -> None:
    """``Down`` on the bottom pane cycles it to the top, still active."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        assert bar._stack.selected_index == 2  # bottom pane "third"

        await pilot.press("down")  # move "third" down past the bottom -> top
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["third", "first", "second"]
        assert bar._stack.selected_index == 0
        assert bar.active_text() == "third"
        assert bar.active_text_area()._vim_mode == "normal"


async def test_ctrl_shift_h_l_no_longer_reorder_panes() -> None:
    """Retired ``Ctrl+Shift+H``/``Ctrl+Shift+L`` no longer reorder panes."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")

        await pilot.press("ctrl+shift+h")  # used to move the active pane up
        await pilot.press("ctrl+shift+l")  # used to move the active pane down
        await pilot.pause()
        await pilot.pause()

        # Reorder moved to Up/Down, so the old chords leave the stack intact.
        assert bar.all_prompt_texts() == ["first", "second", "third"]
        assert bar._stack.selected_index == 2


async def test_single_pane_up_down_keep_cursor_movement() -> None:
    """A single pane has nothing to reorder, so arrows move the cursor."""
    app = _PromptBarApp("alpha\nbeta\ngamma")

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


async def test_comma_is_inert_now_that_stack_keymaps_moved_to_g_prefix() -> None:
    """Bare ``,`` is a prompt-local no-op; the ``g`` prefix owns stack stash/nav.

    The retired comma leader must swallow a lone ``,`` *without* opening a
    leader, stashing, or mutating the stack, while the migrated ``gs`` stash
    still dispatches through the ``g`` prefix.
    """
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

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


# --- add a bottom pane (Ctrl+-) --------------------------------------------


@pytest.mark.parametrize("add_pane_key", ("ctrl+minus", "ctrl+underscore"))
async def test_ctrl_minus_adds_bottom_pane_from_normal(add_pane_key: str) -> None:
    # Textual reports legacy ``0x1f`` as ``ctrl+underscore`` (also Ctrl-hyphen),
    # so this covers both Kitty CSI-u and tmux / legacy terminal paths.
    app = _PromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1

        await pilot.press("escape")
        await pilot.press(add_pane_key)
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["solo prompt", ""]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == ""
        assert app.focused is bar.active_text_area()
        # The fresh pane is ready to type in.
        assert bar.active_text_area()._vim_mode == "insert"


@pytest.mark.parametrize("add_pane_key", ("ctrl+minus", "ctrl+underscore"))
async def test_ctrl_minus_adds_bottom_pane_from_insert(add_pane_key: str) -> None:
    app = _PromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1
        # Default mode is insert; add a pane without leaving insert first.
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press(add_pane_key)
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["solo prompt", ""]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == ""
        assert app.focused is bar.active_text_area()
        # The new pane stays selected in insert mode so the user keeps typing.
        assert bar.active_text_area()._vim_mode == "insert"


async def test_plain_dash_no_longer_adds_pane_in_normal() -> None:
    """The retired ``-`` keymap no longer mutates the stack in normal mode."""
    app = _PromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("-")
        await pilot.pause()
        await pilot.pause()

        # Plain hyphen is inert in normal mode (read-only): no new pane, and the
        # existing prompt text is untouched.
        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["solo prompt"]


@pytest.mark.parametrize("add_pane_key", ("ctrl+minus", "ctrl+underscore"))
async def test_ctrl_minus_is_noop_in_feedback_mode(add_pane_key: str) -> None:
    app = _PromptBarApp("feedback text", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press(add_pane_key)
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["feedback text"]


# --- typed `---` is passive ------------------------------------------------


async def test_typing_separator_stays_passive() -> None:
    """A freshly typed ``---`` line no longer live-splits the active pane."""
    app = _PromptBarApp("foo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        assert len(app.query(".prompt-input")) == 1

        # In insert mode (default): complete a `---` separator line.
        await pilot.press("ctrl+j", "-", "-", "-")
        await pilot.pause()
        await pilot.pause()

        # No split: still one pane, the same pane keeps focus, and the typed
        # separator is preserved verbatim as body text.
        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["foo\n---"]
        assert bar._stack.selected_index == 0
        assert bar.active_text() == "foo\n---"
        assert app.focused is text_area


async def test_typing_separator_stays_passive_in_feedback_mode() -> None:
    app = _PromptBarApp("plan note", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("ctrl+j", "-", "-", "-")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == "plan note\n---"


# --- collision with existing vim keys --------------------------------------


async def test_single_pane_comma_still_reverses_char_search() -> None:
    """In a single pane `,` keeps vim's reverse char-search repeat."""
    app = _PromptBarApp("a) b) c) d")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("f", ")")
        assert text_area.cursor_location == (0, 1)
        await pilot.press("semicolon")
        assert text_area.cursor_location == (0, 4)
        await pilot.press("comma")  # reverse, not a stack leader
        assert text_area.cursor_location == (0, 1)


async def test_multi_pane_comma_reverses_char_search() -> None:
    """In a multi-pane stack `,` reverses char-search; the leader moved to `g`."""
    app = _PromptBarApp("a) b) c)\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("K")  # focus the top pane "a) b) c)"
        await pilot.pause()

        text_area = bar.active_text_area()
        text_area.cursor_location = (0, 0)
        await pilot.press("f", ")")
        assert text_area.cursor_location == (0, 1)
        await pilot.press("semicolon")
        assert text_area.cursor_location == (0, 4)

        # `,` now reverses the search even in a multi-pane stack: the prompt
        # -stack leader migrated to the `g` prefix, so `,` no longer intercepts.
        await pilot.press("comma")
        await pilot.pause()
        assert text_area.cursor_location == (0, 1)
        # Focus did not move.
        assert bar._stack.selected_index == 0


async def test_plain_shift_j_no_longer_joins_lines() -> None:
    """Plain `J` focuses the next pane now; the vim line join is retired."""
    app = _PromptBarApp("top\n---\nlower line\nsecond line")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()  # bottom pane has two lines
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("J")  # would join lines pre-retirement
        await pilot.pause()

        # The bottom pane's text is untouched (no join) and J wrapped focus to
        # the top pane instead.
        assert bar.all_prompt_texts() == ["top", "lower line\nsecond line"]
        assert bar._stack.selected_index == 0
        assert len(app.query(".prompt-input")) == 2
