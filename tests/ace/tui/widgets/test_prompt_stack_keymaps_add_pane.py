"""Prompt-stack keymap tests for adding panes."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._prompt_stack_keymap_helpers import PromptStackKeymapApp


# --- add a bottom pane (NORMAL-mode g-) ------------------------------------


async def test_g_minus_adds_bottom_pane_from_normal() -> None:
    """``g-`` appends an empty bottom pane and drops into it (insert mode)."""
    app = PromptStackKeymapApp("solo prompt")

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
    app = PromptStackKeymapApp("solo prompt")

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
    app = PromptStackKeymapApp("solo prompt")

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
    app = PromptStackKeymapApp("solo prompt")

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
    app = PromptStackKeymapApp("feedback text", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")
        await pilot.press("g", "-")
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert bar.all_prompt_texts() == ["feedback text"]
