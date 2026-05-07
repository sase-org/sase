"""Regression tests for Escape handling in the prompt input bar."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class PromptCancelTestApp(App[None]):
    """Minimal app that records PromptInputBar cancellation messages."""

    def __init__(self, initial_value: str = "") -> None:
        super().__init__()
        self.initial_value = initial_value
        self.cancelled: list[PromptInputBar.Cancelled] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(self.initial_value)

    def on_prompt_input_bar_cancelled(self, event: PromptInputBar.Cancelled) -> None:
        self.cancelled.append(event)


async def test_escape_twice_enters_normal_mode_without_cancelling() -> None:
    """Escape leaves insert mode; a second Escape stays non-destructive."""
    app = PromptCancelTestApp("keep this")
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await pilot.press("escape", "escape")

        assert app.cancelled == []
        assert ta.text == "keep this"
        assert ta._vim_mode == "normal"


async def test_ctrl_c_still_cancels_with_stripped_prompt_text() -> None:
    """Ctrl+C remains the explicit prompt cancellation command."""
    app = PromptCancelTestApp("  cancel me  ")
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")

        assert len(app.cancelled) == 1
        assert app.cancelled[0].cancelled_text == "cancel me"
        assert app.cancelled[0].mode == "prompt"


async def test_escape_clears_pending_operator_without_cancelling() -> None:
    """Escape clears normal-mode operator state without emitting Cancelled."""
    app = PromptCancelTestApp("delete target")
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await pilot.press("escape", "d", "escape")

        assert app.cancelled == []
        assert ta.text == "delete target"
        assert ta._vim_mode == "normal"
        assert ta._pending_operator == ""
