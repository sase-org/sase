"""Tests for the prompt input history trigger."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class PromptHistoryTriggerApp(App[None]):
    """Minimal app that records prompt input messages."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "", mode: str = "prompt") -> None:
        super().__init__()
        self.initial_value = initial_value
        self.mode = mode
        self.history_requests: list[PromptInputBar.HistoryRequested] = []
        self.submissions: list[PromptInputBar.Submitted] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(self.initial_value, mode=self.mode)

    def on_prompt_input_bar_history_requested(
        self, event: PromptInputBar.HistoryRequested
    ) -> None:
        self.history_requests.append(event)

    def on_prompt_input_bar_submitted(self, event: PromptInputBar.Submitted) -> None:
        self.submissions.append(event)


async def test_ctrl_full_stop_requests_history_with_single_line_filter() -> None:
    app = PromptHistoryTriggerApp("fix failing auth test")

    async with app.run_test() as pilot:
        await pilot.press("ctrl+full_stop")

    assert len(app.history_requests) == 1
    request = app.history_requests[0]
    assert request.initial_filter == "fix failing auth test"
    assert request.preserve_prompt_bar is True
    assert request.show_cancelled is False
    assert app.submissions == []


async def test_ctrl_full_stop_noops_for_multiline_prompt() -> None:
    app = PromptHistoryTriggerApp("first line\nsecond line")

    async with app.run_test() as pilot:
        await pilot.press("ctrl+full_stop")

    assert app.history_requests == []
    assert app.submissions == []


async def test_ctrl_full_stop_noops_for_feedback_mode() -> None:
    app = PromptHistoryTriggerApp("plan feedback", mode="feedback")

    async with app.run_test() as pilot:
        await pilot.press("ctrl+full_stop")

    assert app.history_requests == []
    assert app.submissions == []


@pytest.mark.parametrize("prompt", [".", ".x", "#gh:sase .", "#gh:sase .x"])
async def test_dot_history_shortcuts_submit_as_plain_prompt_text(prompt: str) -> None:
    app = PromptHistoryTriggerApp(prompt)

    async with app.run_test() as pilot:
        await pilot.press("enter")

    assert app.history_requests == []
    assert [event.value for event in app.submissions] == [prompt]
    assert app.submissions[0].mode == "prompt"


async def test_open_prompt_history_action_clears_completion_state() -> None:
    app = PromptHistoryTriggerApp("fix failing auth test")

    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area._file_completion_active = True
        text_area._completion_kind = "file"
        text_area._vcs_mru_index = 0

        text_area.action_open_prompt_history()

        assert text_area._file_completion_active is False
        assert text_area._vcs_mru_index is None
