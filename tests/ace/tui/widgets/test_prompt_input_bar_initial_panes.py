"""Tests for seeding ``PromptInputBar`` from an explicit list of panes.

The marked-set kill-and-edit flow (``,x`` with marks) loads each killed agent's
raw prompt into its own pane verbatim, so an embedded ``---`` separator or
leading frontmatter in one agent's prompt must never split that agent across
multiple panes. The existing ``initial_value`` path (history loads, typed
multi-prompts) must keep its canonical ``---`` splitting unchanged.
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _PanesApp(App[None]):
    """Minimal app hosting a prompt bar seeded from explicit panes."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, panes: list[str]) -> None:
        super().__init__()
        self._panes = panes

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_panes=self._panes, id="prompt-input-bar")


class _ValueApp(App[None]):
    """Minimal app hosting a prompt bar seeded from a single string."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, value: str) -> None:
        super().__init__()
        self._value = value

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._value, id="prompt-input-bar")


async def test_initial_panes_one_pane_per_text() -> None:
    app = _PanesApp(["first", "second", "third"])
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar._stack.texts == ["first", "second", "third"]


async def test_initial_panes_does_not_split_embedded_separator() -> None:
    app = _PanesApp(["a\n---\nb", "c"])
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        # The embedded ``---`` stays inside its pane: two agents, two panes.
        assert bar._stack.texts == ["a\n---\nb", "c"]
        assert len(bar._stack) == 2


async def test_initial_panes_keeps_frontmatter_inline() -> None:
    app = _PanesApp(["---\nname: foo\n---\nbody", "next"])
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar._stack.texts == ["---\nname: foo\n---\nbody", "next"]
        assert bar._stack.frontmatter == ""


async def test_initial_value_still_splits_on_separator() -> None:
    app = _ValueApp("a\n---\nb\n---\nc")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        # Unchanged behavior: a typed multi-prompt string splits into panes.
        assert bar._stack.texts == ["a", "b", "c"]


class _CursorApp(App[None]):
    """Host a prompt bar seeded with an explicit pane/cursor."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        markdown: str,
        *,
        selected: int | None = None,
        cursor: tuple[int, int] | None = None,
    ) -> None:
        super().__init__()
        self._markdown = markdown
        self._selected = selected
        self._cursor = cursor

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_xprompt_markdown=self._markdown,
            initial_selected_pane=self._selected,
            initial_cursor=self._cursor,
            id="prompt-input-bar",
        )


async def test_initial_cursor_restores_middle_pane_on_fresh_bar() -> None:
    app = _CursorApp(
        "alpha\n---\nbeta\nline\n---\ngamma",
        selected=1,
        cursor=(1, 2),
    )
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar.all_prompt_texts() == ["alpha", "beta\nline", "gamma"]
        assert bar._stack.selected_index == 1
        text_area = bar.active_text_area()
        assert text_area.cursor_location == (1, 2)
        assert text_area._vim_mode == "insert"


async def test_initial_cursor_clamps_to_document() -> None:
    app = _CursorApp("hello", selected=0, cursor=(9, 9))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar.active_text_area().cursor_location == (0, 5)


async def test_missing_initial_cursor_still_parks_at_end() -> None:
    app = _ValueApp("hello")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert bar.active_text_area().cursor_location == (0, 5)
