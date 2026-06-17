"""Widget-level tests for the prompt-stack keymaps and live splitting.

Covers the multi-agent prompt stack keymaps: pane focus navigation lives on
``Ctrl+Shift+J``/``Ctrl+Shift+K`` and pane reorder on
``Ctrl+Shift+H``/``Ctrl+Shift+L`` (both work in insert and normal mode); the
comma leader stashes panes and ``Ctrl+-`` adds a new bottom pane; typing a
``---`` separator line in insert mode splits the active pane into stacked panes;
and
the comma leader coexists with vim's reverse char-search repeat and the normal
``J`` line join.
"""

from __future__ import annotations

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


# --- pane focus navigation (Ctrl+Shift+J / Ctrl+Shift+K) -------------------


async def test_ctrl_shift_k_focuses_previous_pane_from_normal() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2

        await pilot.press("escape")  # active (bottom) pane -> normal mode
        await pilot.press("ctrl+shift+k")  # focus the pane above
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"
        assert app.focused is bar.active_text_area()
        # Navigating from normal mode keeps the target pane in normal mode.
        assert bar.active_text_area()._vim_mode == "normal"


async def test_ctrl_shift_navigation_from_insert_keeps_insert_mode() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Default mode is insert; navigate up while still "typing".
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("ctrl+shift+k")  # 2 -> 1
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"
        assert app.focused is bar.active_text_area()
        # The target pane stays in insert mode so the user keeps typing.
        assert bar.active_text_area()._vim_mode == "insert"


async def test_ctrl_shift_j_then_k_round_trips_focus() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("ctrl+shift+k")  # 2 -> 1
        await pilot.press("ctrl+shift+k")  # 1 -> 0
        await pilot.pause()
        assert bar._stack.selected_index == 0
        assert bar.active_text() == "first"

        await pilot.press("ctrl+shift+j")  # 0 -> 1
        await pilot.pause()
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"


async def test_navigation_clamps_at_edges() -> None:
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        # Already at the bottom: Ctrl+Shift+J is a no-op.
        await pilot.press("ctrl+shift+j")
        await pilot.pause()
        assert bar._stack.selected_index == 1


# --- reorder (Ctrl+Shift+H / Ctrl+Shift+L) ---------------------------------


async def test_ctrl_shift_h_moves_active_pane_up() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("ctrl+shift+h")  # move "third" higher/earlier
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["first", "third", "second"]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "third"
        # The moved pane stays active and in normal mode for repeated reorders.
        assert bar.active_text_area()._vim_mode == "normal"


async def test_ctrl_shift_l_moves_active_pane_down() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("ctrl+shift+k")  # focus "second" (index 1)
        await pilot.pause()
        await pilot.press("ctrl+shift+l")  # move "second" lower/later
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
        await pilot.press("ctrl+shift+h")  # move "second!" higher/earlier
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["second!", "first"]


async def test_insert_mode_reorder_keeps_insert_mode() -> None:
    """Reordering from insert mode returns the moved pane to insert mode."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Default mode is insert; reorder without dropping into normal mode.
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("ctrl+shift+h")  # move "third" higher/earlier
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["first", "third", "second"]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == "third"
        # The moved pane stays in insert mode so the user keeps typing.
        assert bar.active_text_area()._vim_mode == "insert"


async def test_comma_jk_no_longer_reorders_but_other_leaders_work() -> None:
    """Retired `,j`/`,k`/`,J`/`,K` no-op; other comma-leader actions still fire."""
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        assert bar._stack.selected_index == 2

        # Pane reorder lives on Ctrl+Shift+H/L now, so every comma-leader J/K
        # case (both cases) is a swallowed no-op that leaves the stack intact.
        for key in ("j", "k", "J", "K"):
            await pilot.press("comma", key)
            await pilot.pause()
        assert bar.all_prompt_texts() == ["first", "second", "third"]
        assert bar._stack.selected_index == 2

        # A surviving comma-leader action (`,s` stash) still dispatches: it drops
        # the active bottom pane, proving the leader itself is unaffected.
        await pilot.press("comma", "s")
        await pilot.pause()
        await pilot.pause()
        assert bar.all_prompt_texts() == ["first", "second"]


# --- add a bottom pane (Ctrl+-) --------------------------------------------


async def test_ctrl_minus_adds_bottom_pane_from_normal() -> None:
    app = _PromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1

        await pilot.press("escape")
        await pilot.press("ctrl+minus")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["solo prompt", ""]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == ""
        assert app.focused is bar.active_text_area()
        # The fresh pane is ready to type in.
        assert bar.active_text_area()._vim_mode == "insert"


async def test_ctrl_minus_adds_bottom_pane_from_insert() -> None:
    app = _PromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1
        # Default mode is insert; add a pane without leaving insert first.
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("ctrl+minus")
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


async def test_ctrl_minus_is_noop_in_feedback_mode() -> None:
    app = _PromptBarApp("feedback text", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("ctrl+minus")
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["feedback text"]


# --- live split (typed `---`) ----------------------------------------------


async def test_typing_separator_splits_into_new_pane() -> None:
    app = _PromptBarApp("foo")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1

        # In insert mode (default): complete a `---` separator line.
        await pilot.press("ctrl+j", "-", "-", "-")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 2
        assert bar.all_prompt_texts() == ["foo", ""]
        assert bar._stack.selected_index == 1
        assert bar.active_text() == ""
        assert app.focused is bar.active_text_area()


async def test_typing_separator_does_not_split_feedback_mode() -> None:
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


async def test_multi_pane_comma_is_leader_not_char_search() -> None:
    """In a multi-pane stack `,` is the stack leader, not char-search reverse."""
    app = _PromptBarApp("a) b) c)\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("ctrl+shift+k")  # focus the top pane "a) b) c)"
        await pilot.pause()

        text_area = bar.active_text_area()
        text_area.cursor_location = (0, 0)
        await pilot.press("f", ")")
        assert text_area.cursor_location == (0, 1)
        await pilot.press("semicolon")
        assert text_area.cursor_location == (0, 4)

        # `,` here opens the stack leader; it must NOT reverse the search.
        await pilot.press("comma")
        await pilot.pause()
        assert text_area.cursor_location == (0, 4)
        # Escape abandons a dangling leader harmlessly.
        await pilot.press("escape")
        assert bar._stack.selected_index == 0


async def test_plain_shift_j_joins_lines_within_active_pane() -> None:
    """Plain `J` still joins lines; pane reorder lives on Ctrl+Shift+H/L."""
    app = _PromptBarApp("top\n---\nlower line\nsecond line")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()  # bottom pane has two lines
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("J")
        await pilot.pause()

        assert bar.active_text() == "lower line second line"
        # The stack is unchanged: still two panes.
        assert len(app.query(".prompt-input")) == 2
