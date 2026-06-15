"""Widget-level tests for the multi-agent prompt stack rendering (Phase 2).

Covers the Phase 2 deliverable of ``PromptInputBar``: initial text containing
``---`` separators renders as stacked panes, single prompts (including ones with
YAML frontmatter) stay a single verbatim pane, the stack-aware helper APIs read
the live panes, and the stack height stays within the terminal with the active
pane growing while inactive panes compact.
"""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


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


def _height(value: Any) -> int:
    """Return a numeric height from a Textual style value."""
    return int(getattr(value, "value", value))


def _pane_heights(app: _PromptBarApp, bar: PromptInputBar) -> list[int]:
    """Return the content height of each pane, top-to-bottom."""
    heights: list[int] = []
    for item in bar._stack.items:
        pane = app.query_one(f"#{bar._pane_id(item)}", PromptTextArea)
        heights.append(_height(pane.styles.height))
    return heights


# --- single-pane rendering is unchanged -----------------------------------


async def test_single_prompt_renders_one_solo_pane() -> None:
    app = _PromptBarApp("just one prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        panes = app.query(".prompt-input")
        assert len(panes) == 1
        assert not app.query(".prompt-stack-separator")
        pane = app.query_one(".prompt-input", PromptTextArea)
        assert "solo" in pane.classes
        assert pane.text == "just one prompt"
        assert app.focused is pane


async def test_single_prompt_with_frontmatter_stays_verbatim() -> None:
    initial = "---\nmodel: opus\n---\ndo the thing"
    app = _PromptBarApp(initial)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        bar = app.query_one(PromptInputBar)
        # Frontmatter is NOT stripped for a single prompt; the pane is verbatim.
        assert bar.active_text() == initial


# --- multi-pane rendering --------------------------------------------------


async def test_initial_separators_render_stacked_panes() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        panes = app.query(".prompt-input")
        assert len(panes) == 3
        assert len(app.query(".prompt-stack-separator")) == 3
        assert bar.all_prompt_texts() == ["first", "second", "third"]
        # Bottom pane is the default active pane and owns focus.
        assert bar._stack.selected_index == 2
        assert app.focused is bar.active_text_area()
        assert bar.active_text() == "third"
        assert "active" in bar.active_text_area().classes


async def test_panes_have_unique_ids() -> None:
    app = _PromptBarApp("a\n---\nb\n---\nc")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        ids = [pane.id for pane in app.query(".prompt-input")]
        assert len(ids) == len(set(ids)) == 3


async def test_current_prompt_text_joins_whole_stack() -> None:
    app = _PromptBarApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar.current_prompt_text() == "alpha\n---\nbeta"


async def test_current_prompt_text_reflects_live_edits() -> None:
    app = _PromptBarApp("alpha\n---\nbeta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        # Type into the active (bottom) pane.
        await pilot.press("!")
        await pilot.pause()

        assert bar.active_text() == "beta!"
        assert bar.all_prompt_texts() == ["alpha", "beta!"]
        assert bar.current_prompt_text() == "alpha\n---\nbeta!"


async def test_multi_prompt_with_frontmatter_preserved_on_join() -> None:
    app = _PromptBarApp("---\nmodel: opus\n---\nalpha\n---\nbeta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert bar.all_prompt_texts() == ["alpha", "beta"]
        joined = bar.current_prompt_text()
        assert joined == "---\nmodel: opus\n---\nalpha\n---\nbeta"


async def test_fenced_separator_does_not_split() -> None:
    initial = "before\n```\n---\nstill code\n```\nafter"
    app = _PromptBarApp(initial)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == initial


# --- height behavior -------------------------------------------------------


async def test_stack_height_capped_by_terminal_and_active_grows() -> None:
    long = "word " * 60  # wraps to many rows in a narrow terminal
    app = _PromptBarApp(f"short top\n---\nshort middle\n---\n{long}")

    async with app.run_test(size=(40, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        heights = _pane_heights(app, bar)
        active = bar._stack.selected_index

        # The whole bar fits within the terminal (minus the reserved margin).
        assert _height(bar.styles.height) <= app.screen.size.height - 2
        # The active (long) bottom pane grows; the short inactive panes compact.
        assert heights[active] > max(heights[0], heights[1])


async def test_inactive_panes_compact_first() -> None:
    long = "word " * 60
    # Two long panes; only the active one is allowed to grow tall.
    app = _PromptBarApp(f"{long}\n---\n{long}")

    async with app.run_test(size=(40, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        heights = _pane_heights(app, bar)
        active = bar._stack.selected_index
        inactive = 1 - active

        assert heights[active] > heights[inactive]
        assert _height(bar.styles.height) <= app.screen.size.height - 2


# --- focus + rebuild -------------------------------------------------------


async def test_focus_item_moves_active_pane() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.focus_item(0)
        await pilot.pause()
        await pilot.pause()

        assert bar._stack.selected_index == 0
        assert app.focused is bar.active_text_area()
        assert bar.active_text() == "first"


async def test_load_stack_from_text_rebuilds_panes() -> None:
    app = _PromptBarApp("only one")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1

        bar.load_stack_from_text("uno\n---\ndos\n---\ntres")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 3
        assert bar.all_prompt_texts() == ["uno", "dos", "tres"]
        assert app.focused is bar.active_text_area()

        # And back down to a single pane.
        bar.load_stack_from_text("collapsed")
        await pilot.pause()
        await pilot.pause()

        assert len(app.query(".prompt-input")) == 1
        assert "solo" in app.query_one(".prompt-input", PromptTextArea).classes
        assert bar.active_text() == "collapsed"


# --- mode guards -----------------------------------------------------------


async def test_feedback_mode_never_splits() -> None:
    app = _PromptBarApp("a\n---\nb", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        assert len(app.query(".prompt-input")) == 1
        assert bar.active_text() == "a\n---\nb"
