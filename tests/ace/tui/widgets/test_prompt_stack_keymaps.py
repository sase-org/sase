"""Widget-level tests for the prompt-stack keymaps.

Covers the multi-agent prompt stack keymaps: pane focus navigation lives on the
prompt ``g`` prefix ``gj`` (next/lower) / ``gk`` (prev/higher) and pane reorder
on ``gJ`` (lower/later) / ``gK`` (higher/earlier) -- all NORMAL-mode-only.  Bare
normal-mode ``J`` is once again vim's line join and bare ``K`` is a swallowed
no-op, while normal-mode ``Up``/``Down`` move the cursor (no pane reorder).
NORMAL-mode ``g-`` adds a new bottom pane; a typed ``---`` separator line is
inert (panes are created only through ``g-``); the prompt stash/structural
keymaps migrated to the ``g`` prefix, so ``,`` is now a prompt-local no-op that
still defers to vim's reverse char-search repeat; and the retired structural
chords (``Ctrl+-``/``ctrl+underscore`` add-pane, ``Ctrl+H``/``Ctrl+L`` focus,
``Ctrl+Shift+H``/``Ctrl+Shift+L`` reorder) no longer fire.
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


# --- pane focus navigation (NORMAL-mode gj / gk) ---------------------------


async def test_gk_focuses_previous_pane_from_normal() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2

        await pilot.press("escape")  # active (bottom) pane -> normal mode
        await pilot.press("g", "k")  # focus the pane above
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"
        assert app.focused is bar.active_text_area()
        # Focus navigation keeps the target pane in normal mode.
        assert bar.active_text_area()._vim_mode == "normal"


async def test_gk_then_gj_round_trips_focus() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "k")  # 2 -> 1
        await pilot.press("g", "k")  # 1 -> 0
        await pilot.pause()
        assert bar._stack.selected_index == 0
        assert bar.active_text() == "first"

        await pilot.press("g", "j")  # 0 -> 1
        await pilot.pause()
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"


async def test_gk_cycles_from_top_to_bottom() -> None:
    """``gk`` from the top pane wraps focus around to the bottom pane."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "k")  # 2 -> 1
        await pilot.press("g", "k")  # 1 -> 0 (top pane)
        await pilot.pause()
        assert bar._stack.selected_index == 0

        await pilot.press("g", "k")  # 0 -> 2 (wraps to the bottom pane)
        await pilot.pause()
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "third"
        # Cycling preserves normal mode.
        assert bar.active_text_area()._vim_mode == "normal"


async def test_gj_focuses_next_pane_and_cycles_at_bottom_edge() -> None:
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "k")  # 1 -> 0 (focus the top pane)
        await pilot.pause()
        assert bar._stack.selected_index == 0

        await pilot.press("g", "j")  # 0 -> 1 (focus the bottom pane)
        await pilot.pause()
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"

        # From the bottom pane gj wraps around to the top pane.
        await pilot.press("g", "j")  # 1 -> 0
        await pilot.pause()
        assert bar._stack.selected_index == 0
        assert bar.active_text() == "first"


async def test_g_prefix_nav_is_normal_mode_only() -> None:
    """``gj``/``gk`` are NORMAL-mode-only: in insert mode they type literally."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Default mode is insert; the bottom pane is active.
        assert bar.active_text_area()._vim_mode == "insert"
        assert bar._stack.selected_index == 2

        await pilot.press("g", "k")
        await pilot.press("g", "j")
        await pilot.pause()

        # Focus never moved; the keys were inserted as ordinary characters.
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "thirdgkgj"


# --- bare J / K regressions ------------------------------------------------


async def test_bare_j_joins_active_pane_lines_and_does_not_focus() -> None:
    """Bare normal-mode ``J`` joins lines in the active pane; it never focuses.

    Pane focus moved to ``gj``/``gk``, so vim's line join is restored on bare
    ``J``: it collapses the active pane's lines instead of navigating panes.
    """
    app = _PromptBarApp("top\n---\nlower line\nsecond line")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()  # bottom pane has two lines
        assert bar._stack.selected_index == 1
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("J")  # vim line join, restored in this phase
        await pilot.pause()

        # The active pane's two lines were joined with a single space; focus
        # stayed on the bottom pane (no pane navigation).
        assert bar.all_prompt_texts() == ["top", "lower line second line"]
        assert bar._stack.selected_index == 1
        assert app.focused is text_area


async def test_bare_j_join_supports_count() -> None:
    """A counted ``3J`` joins three lines in the active pane."""
    app = _PromptBarApp("one\ntwo\nthree\nfour")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("3", "J")
        await pilot.pause()

        assert bar.active_text() == "one two three\nfour"


async def test_bare_k_does_not_focus_pane_or_bubble() -> None:
    """Bare normal-mode ``K`` is a swallowed prompt-local no-op (no focus move).

    With pane focus on ``gj``/``gk``, bare ``K`` has no prompt command, so it is
    swallowed -- it neither navigates panes, inserts text, nor bubbles to the
    app-level ``K`` panel-focus binding while the prompt body owns focus.
    """
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        assert bar._stack.selected_index == 2

        await pilot.press("K")
        await pilot.pause()

        # Focus did not move to another pane and ``K`` was not inserted as text.
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "third"
        assert app.focused is text_area


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

        # Focus navigation moved to gj/gk, so the old chords are inert.
        assert bar._stack.selected_index == 2
        assert bar.active_text() == "third"


async def test_ctrl_l_does_not_focus_pane_when_consumed_by_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insert-mode ``Ctrl+L`` still accepts a soft completion and never focuses.

    Pane focus lives on the NORMAL-mode ``gj``/``gk`` keys, so ``Ctrl+L`` has no
    pane-focus fallback -- it only accepts a soft completion (and otherwise
    falls through to the app-level ``dismiss_toasts`` binding).
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


# --- reorder (NORMAL-mode gK / gJ) -----------------------------------------


async def test_gk_moves_active_pane_higher() -> None:
    """``gK`` moves the active pane higher/earlier."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

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


async def test_gj_moves_active_pane_lower() -> None:
    """``gJ`` moves the active pane lower/later."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

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
    app = _PromptBarApp("first\n---\nsecond")

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
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

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
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

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
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

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
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

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


async def test_multi_pane_normal_arrows_move_cursor_not_panes() -> None:
    """Normal-mode ``Up``/``Down`` move the cursor; reorder moved to gJ/gK.

    Removing the old normal-mode arrow reorder special case means a multi-pane
    stack regains ordinary TextArea cursor movement on the arrows.
    """
    app = _PromptBarApp("first\n---\nalpha\nbeta\ngamma")

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


# --- add a bottom pane (NORMAL-mode g-) ------------------------------------


async def test_g_minus_adds_bottom_pane_from_normal() -> None:
    """``g-`` appends an empty bottom pane and drops into it (insert mode)."""
    app = _PromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1

        await pilot.press("escape")
        await pilot.press("g", "-")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["solo prompt", ""]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == ""
        assert app.focused is bar.active_text_area()
        # The fresh pane is ready to type in.
        assert bar.active_text_area()._vim_mode == "insert"


async def test_g_minus_is_normal_mode_only() -> None:
    """``g-`` is NORMAL-mode-only: in insert mode the keys type literally."""
    app = _PromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Default mode is insert; ``g`` then ``-`` are ordinary characters.
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("g", "-")
        await pilot.pause()
        await pilot.pause()

        # No new pane: the chord was typed into the active pane verbatim.
        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["solo promptg-"]


async def test_plain_dash_no_longer_adds_pane_in_normal() -> None:
    """A bare ``-`` (no ``g`` prefix) does not mutate the stack in normal mode."""
    app = _PromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("-")
        await pilot.pause()
        await pilot.pause()

        # Plain hyphen is inert in normal mode (read-only): no new pane, and the
        # existing prompt text is untouched.  Add-pane lives on ``g-`` now.
        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["solo prompt"]


@pytest.mark.parametrize("add_pane_key", ("ctrl+minus", "ctrl+underscore"))
async def test_ctrl_minus_no_longer_adds_pane(add_pane_key: str) -> None:
    """The retired ``Ctrl+-`` / ``ctrl+underscore`` chords no longer add a pane.

    Textual reports legacy ``0x1f`` as ``ctrl+underscore`` (also Ctrl-hyphen),
    so this covers both the Kitty CSI-u and tmux / legacy terminal paths; both
    are inert now that add-pane migrated to the NORMAL-mode ``g-`` keymap.
    """
    app = _PromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1

        # From insert (the old chord worked while typing) ...
        await pilot.press(add_pane_key)
        await pilot.pause()
        await pilot.pause()
        # ... and from normal (the old chord worked while browsing too).
        await pilot.press("escape")
        await pilot.press(add_pane_key)
        await pilot.pause()
        await pilot.pause()

        # Still a single pane: the legacy chord adds nothing in either mode.
        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["solo prompt"]


async def test_g_minus_is_noop_in_feedback_mode() -> None:
    app = _PromptBarApp("feedback text", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "-")
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
        await pilot.press("g", "k")  # focus the top pane "a) b) c)"
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
