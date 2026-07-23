"""Shared support for prompt-stack submit and cancel widget tests."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.pilot import Pilot

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class CaptureApp(App[None]):
    """Host a prompt bar and record its submit, cancel, and stash messages."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self.submitted: list[PromptInputBar.Submitted] = []
        self.cancelled: list[PromptInputBar.Cancelled] = []
        self.stashed: list[PromptInputBar.Stashed] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )

    def on_prompt_input_bar_submitted(self, event: PromptInputBar.Submitted) -> None:
        self.submitted.append(event)

    def on_prompt_input_bar_cancelled(self, event: PromptInputBar.Cancelled) -> None:
        self.cancelled.append(event)

    def on_prompt_input_bar_stashed(self, event: PromptInputBar.Stashed) -> None:
        self.stashed.append(event)


async def submit_current_pane(
    pilot: Pilot[None],
    bar: PromptInputBar,
    route: str,
) -> None:
    """Submit the selected pane through the direct or chooser route."""
    if route == "direct":
        if bar.active_text_area()._vim_mode == "insert":
            await pilot.press("escape")
        await pilot.press("g", "enter")
    else:
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("c")
    await pilot.pause()
    await pilot.pause()
