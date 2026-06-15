"""Tests for prompt history request handling from the prompt bar."""

from __future__ import annotations

from sase.ace.tui.actions.agent_workflow._prompt_bar_requests import (
    PromptBarRequestsMixin,
)
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


def _ctx() -> PromptContext:
    return PromptContext(
        project_name="proj",
        cl_name="cl",
        project_file="/tmp/proj.sase",
        workspace_dir="/tmp/ws",
        workspace_num=1,
        workflow_name="ace(run)-ts",
        timestamp="ts",
        history_sort_key="branch",
        display_name="proj",
        update_target="",
        is_home_mode=False,
    )


class _TextArea:
    def __init__(self) -> None:
        self.focus_count = 0

    def focus(self) -> None:
        self.focus_count += 1


class _Bar:
    def __init__(self, text_area: _TextArea) -> None:
        self.text_area = text_area

    def active_text_area(self) -> _TextArea:
        return self.text_area


class _HistoryRequestHarness(PromptBarRequestsMixin):
    def __init__(self) -> None:
        self._prompt_context: PromptContext | None = _ctx()
        self.text_area = _TextArea()
        self.bar = _Bar(self.text_area)
        self.pushed: list[tuple[object, object]] = []
        self.notifications: list[tuple[str, str | None]] = []
        self.unmount_count = 0

    def push_screen(self, modal: object, callback: object) -> None:
        self.pushed.append((modal, callback))

    def query_one(self, _selector: str, _cls: type[PromptInputBar]) -> _Bar:
        return self.bar

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _unmount_prompt_bar(self) -> None:
        self.unmount_count += 1


def test_ctrl_k_history_cancel_refocuses_prompt_bar_without_unmounting() -> None:
    harness = _HistoryRequestHarness()
    event = PromptInputBar.HistoryRequested(
        initial_filter="draft prompt",
        preserve_prompt_bar=True,
    )

    harness.on_prompt_input_bar_history_requested(event)
    modal, callback = harness.pushed[0]
    callback(None)

    assert modal._initial_filter == "draft prompt"
    assert harness.text_area.focus_count == 1
    assert harness.unmount_count == 0
    assert harness.notifications == []
    assert harness._prompt_context is not None
