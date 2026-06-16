"""Tests for seeding ``PromptInputBar`` from an explicit list of panes.

The bulk kill-and-edit flow (``,X``) loads each killed agent's raw prompt into
its own pane verbatim, so an embedded ``---`` separator or leading frontmatter
in one agent's prompt must never split that agent across multiple panes. The
existing ``initial_value`` path (history loads, typed multi-prompts) must keep
its canonical ``---`` splitting unchanged.
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
