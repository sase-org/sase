"""Prompt-stack keymap tests for focus navigation and retired focus chords.

Covers the multi-agent prompt stack focus keymaps: pane focus navigation lives
on the prompt ``g`` prefix ``gj`` (next/lower) / ``gk`` (prev/higher) and is
NORMAL-mode-only. Bare normal-mode ``J`` is once again vim's line join and bare
``K`` is the prompt preview lookup command. The retired ``Ctrl+H``/``Ctrl+L``
focus chords no longer fire.
"""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._prompt_stack_keymap_helpers import PromptStackKeymapApp


# --- pane focus navigation (NORMAL-mode gj / gk) ---------------------------


async def test_gk_focuses_previous_pane_from_normal() -> None:
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

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


async def test_ctrl_gk_focuses_previous_pane_from_normal_and_keeps_normal() -> None:
    """NORMAL-mode ``Ctrl+G k`` mirrors ``gk``: focus the pane above, stay NORMAL."""
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2

        await pilot.press("escape")  # active (bottom) pane -> normal mode
        await pilot.press("ctrl+g", "k")  # focus the pane above via the ^G prefix
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"
        assert app.focused is bar.active_text_area()
        # NORMAL-mode ``Ctrl+G`` nav keeps the target pane in normal mode, unlike
        # the INSERT-mode ``Ctrl+G`` prefix which keeps it in insert mode.
        assert bar.active_text_area()._vim_mode == "normal"


async def test_ctrl_gk_focuses_previous_pane_from_insert_and_keeps_insert() -> None:
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar._stack.selected_index == 2
        assert bar.active_text_area()._vim_mode == "insert"

        await pilot.press("ctrl+g", "k")
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert bar.active_text() == "second"
        assert app.focused is bar.active_text_area()
        assert bar.active_text_area()._vim_mode == "insert"


async def test_gk_then_gj_round_trips_focus() -> None:
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

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
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

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
    app = PromptStackKeymapApp("first\n---\nsecond")

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
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

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
    app = PromptStackKeymapApp("top\n---\nlower line\nsecond line")

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
    app = PromptStackKeymapApp("one\ntwo\nthree\nfour")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("3", "J")
        await pilot.pause()

        assert bar.active_text() == "one two three\nfour"


async def test_bare_k_without_lookup_target_does_not_focus_pane_or_bubble() -> None:
    """Bare normal-mode ``K`` stays prompt-local when no lookup target exists.

    With pane focus on ``gj``/``gk``, bare ``K`` is the preview command. When the
    cursor is on an identifier rather than a previewable token or plain word,
    it neither navigates panes, inserts text, nor bubbles to the app-level
    ``K`` panel-focus binding while the prompt body owns focus.
    """
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird_value")

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
        assert bar.active_text() == "third_value"
        assert app.focused is text_area


async def test_ctrl_h_l_no_longer_focus_panes() -> None:
    """Retired ``Ctrl+H``/``Ctrl+L`` no longer move pane focus."""
    app = PromptStackKeymapApp("first\n---\nsecond\n---\nthird")

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
    app = PromptStackKeymapApp("first\n---\nsecond")

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
