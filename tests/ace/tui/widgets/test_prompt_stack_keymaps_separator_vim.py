"""Prompt-stack keymap tests for passive separators and vim key collisions.

Covers typed ``---`` separator lines staying inert and ``,`` remaining vim's
reverse char-search repeat now that prompt stash/structural keymaps live on the
``g`` prefix.
"""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._prompt_stack_keymap_helpers import PromptStackKeymapApp


# --- typed `---` is passive ------------------------------------------------


async def test_typing_separator_stays_passive() -> None:
    """A freshly typed ``---`` line no longer live-splits the active pane."""
    app = PromptStackKeymapApp("foo")

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
    app = PromptStackKeymapApp("plan note", mode="feedback")

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
    app = PromptStackKeymapApp("a) b) c) d")

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
    app = PromptStackKeymapApp("a) b) c)\n---\nsecond")

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
