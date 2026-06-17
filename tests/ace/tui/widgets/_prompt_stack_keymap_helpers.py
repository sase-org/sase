"""Shared helpers for prompt-stack keymap tests."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class PromptStackKeymapApp(App[None]):
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
