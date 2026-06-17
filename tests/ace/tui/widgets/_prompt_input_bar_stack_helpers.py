"""Shared helpers for prompt input bar stack widget tests."""

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


class _RecordingPromptBarApp(App[None]):
    """Host a prompt bar and record the editor messages it posts.

    Carries the app-level ``ctrl+g`` binding too, so a test can prove the
    focused pane's widget-local ``ctrl+g`` shadows it instead of triggering the
    global "edit last VCS xprompt" action.
    """

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [("ctrl+g", "start_last_vcs_xprompt_in_editor", "Edit last VCS")]

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self.editor_requests: list[PromptInputBar.EditorRequested] = []
        self.all_editor_requests: list[PromptInputBar.AllEditorRequested] = []
        self.global_editor_calls = 0

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )

    def on_prompt_input_bar_editor_requested(
        self, event: PromptInputBar.EditorRequested
    ) -> None:
        self.editor_requests.append(event)

    def on_prompt_input_bar_all_editor_requested(
        self, event: PromptInputBar.AllEditorRequested
    ) -> None:
        self.all_editor_requests.append(event)

    def action_start_last_vcs_xprompt_in_editor(self) -> None:
        self.global_editor_calls += 1


class _XPromptMarkdownApp(App[None]):
    """Minimal app that seeds a bar with editor-file (xprompt markdown) text."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, markdown: str) -> None:
        super().__init__()
        self._markdown = markdown

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_xprompt_markdown=self._markdown,
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
