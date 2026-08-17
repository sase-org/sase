"""App-handler tests for Phase 4 stack submit / cancel routing + lifecycle.

These pin the contracts the launch path depends on:

- A single-pane (``keep_bar``) submit launches the selected pane but does NOT
  unmount the bar or clear the base prompt context, and never routes the
  remaining panes through the cancel-save safety net.
- A whole-stack submit unmounts and launches the joined multi-prompt.
- A per-pane ``<ctrl+c>`` records only the cancelled pane's text as cancelled
  history and keeps the bar mounted.
- ``_finish_agent_launch(keep_bar=True)`` clones an independent launch context
  per submit (fresh timestamp / workflow name) and leaves the base untouched,
  so back-to-back single submits never race on ``self._prompt_context``.
  Assertions inspect the recorded ``_submit_launch_proc`` prompt and payload.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.actions._event_base import EventHandlersBase
from sase.ace.tui.actions.agent_workflow._prompt_bar_submit import (
    PromptBarSubmitMixin,
)
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.history.prompt import is_recordable_prompt

from tests.ace.tui._agent_launch_helpers import _FakeApp


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


class _SubmitHarness(PromptBarSubmitMixin):
    """Drive the submit/cancel handlers without a live Textual DOM."""

    def __init__(self) -> None:
        self._prompt_context: PromptContext | None = _ctx()
        self._plan_feedback_context = None
        self._approve_prompt_context = None
        self.finish_calls: list[tuple[str, bool]] = []
        self.saved_cancelled: list[str] = []
        self.saved_record_segments: list[bool] = []
        self.unmount_calls = 0
        self.unmount_without_save_calls = 0
        self.unmount_return = "stored prompt"
        self.notifications: list[tuple[str, str | None, str | None]] = []

    def notify(
        self,
        msg: str,
        *,
        severity: str | None = None,
        title: str | None = None,
    ) -> None:
        self.notifications.append((msg, severity, title))

    def _finish_agent_launch(self, prompt: str, *, keep_bar: bool = False) -> None:
        self.finish_calls.append((prompt, keep_bar))

    def _save_text_as_cancelled(
        self,
        text: str,
        *,
        record_segments: bool = True,
    ) -> str:
        self.saved_cancelled.append(text)
        self.saved_record_segments.append(record_segments)
        stripped = text.strip()
        return stripped if is_recordable_prompt(stripped) else ""

    def _unmount_prompt_bar(self) -> str:
        self.unmount_calls += 1
        return self.unmount_return

    def _unmount_prompt_bar_without_cancel_save(self) -> None:
        self.unmount_without_save_calls += 1


class _KeepBarGateApp(EventHandlersBase, _FakeApp):
    def __init__(self) -> None:
        _FakeApp.__init__(self)
        self._screen_stack = [object()]
        self.current_tab = "agents"
        self.screen = object()
        self._prompt_editor_suspended = False

    def query(self, selector: Any) -> list[object]:
        if selector is PromptInputBar:
            return [object()]
        return []


# --- submit routing --------------------------------------------------------


def test_single_pane_submit_keeps_bar_and_context() -> None:
    harness = _SubmitHarness()

    harness.on_prompt_input_bar_submitted(
        PromptInputBar.Submitted("pane text", "prompt", keep_bar=True)
    )

    assert harness.finish_calls == [("pane text", True)]
    assert harness.unmount_calls == 0
    assert harness._prompt_context is not None  # base preserved for next submit


def test_whole_stack_submit_routes_joined_prompt() -> None:
    harness = _SubmitHarness()

    harness.on_prompt_input_bar_submitted(
        PromptInputBar.Submitted(
            "a\n---\nb", "prompt", whole_stack=True, keep_bar=False
        )
    )

    assert harness.finish_calls == [("a\n---\nb", False)]
    assert harness.unmount_calls == 0  # _finish_agent_launch owns the unmount


def test_empty_whole_bar_submit_unmounts_and_clears_context() -> None:
    harness = _SubmitHarness()

    harness.on_prompt_input_bar_submitted(PromptInputBar.Submitted("", "prompt"))

    assert harness.finish_calls == []
    assert harness.unmount_calls == 1
    assert harness._prompt_context is None
    assert harness.notifications == [("Empty prompt - cancelled", "warning", None)]


# --- cancel routing --------------------------------------------------------


def test_per_pane_cancel_saves_only_that_pane_and_keeps_bar() -> None:
    harness = _SubmitHarness()

    harness.on_prompt_input_bar_cancelled(
        PromptInputBar.Cancelled(
            "cancelled pane text right now", "prompt", keep_bar=True
        )
    )

    assert harness.saved_cancelled == ["cancelled pane text right now"]
    assert harness.saved_record_segments == [True]
    assert harness.unmount_calls == 0
    assert harness.unmount_without_save_calls == 0
    assert harness._prompt_context is not None
    assert harness.notifications == [
        (
            '"cancelled pane text right now"',
            None,
            "Prompt pane cancelled — saved to history",
        )
    ]


def test_per_pane_cancel_skips_toast_when_text_was_not_stored() -> None:
    harness = _SubmitHarness()

    harness.on_prompt_input_bar_cancelled(
        PromptInputBar.Cancelled("#gh:sase", "prompt", keep_bar=True)
    )

    assert harness.saved_cancelled == ["#gh:sase"]
    assert harness.saved_record_segments == [True]
    assert harness.notifications == []


def test_all_pane_cancel_saves_single_joined_entry_and_detaches_once() -> None:
    harness = _SubmitHarness()

    harness.on_prompt_input_bar_cancelled(
        PromptInputBar.Cancelled(
            "first pane cancelled now\n---\nsecond pane cancelled now",
            "prompt",
            record_segments=False,
        )
    )

    assert harness.saved_cancelled == [
        "first pane cancelled now\n---\nsecond pane cancelled now"
    ]
    assert harness.saved_record_segments == [False]
    assert harness.unmount_calls == 0
    assert harness.unmount_without_save_calls == 1
    assert harness._prompt_context is None
    assert harness.notifications == [
        (
            '"first pane cancelled now --- second pane cancelled now"',
            None,
            "Prompt input cancelled — saved to history",
        )
    ]


def test_whole_bar_cancel_unmounts_and_clears_context() -> None:
    harness = _SubmitHarness()
    harness.unmount_return = "fix bug"

    harness.on_prompt_input_bar_cancelled(PromptInputBar.Cancelled("text", "prompt"))

    # The whole-bar cancel saves through the unmount safety net, not the
    # explicit per-pane save helper.
    assert harness.saved_cancelled == []
    assert harness.saved_record_segments == []
    assert harness.unmount_calls == 1
    assert harness.unmount_without_save_calls == 0
    assert harness._prompt_context is None
    assert harness.notifications == [
        (
            '"fix bug"',
            None,
            "Prompt input cancelled — saved to history",
        )
    ]


def test_whole_bar_cancel_skips_toast_when_text_was_not_stored() -> None:
    harness = _SubmitHarness()
    harness.unmount_return = ""

    harness.on_prompt_input_bar_cancelled(
        PromptInputBar.Cancelled("#gh:sase", "prompt")
    )

    assert harness.unmount_calls == 1
    assert harness.unmount_without_save_calls == 0
    assert harness._prompt_context is None
    assert harness.notifications == []


def test_cancel_toast_uses_short_preview_for_long_prompts() -> None:
    harness = _SubmitHarness()
    harness.unmount_return = " ".join(["longprompt"] * 12)

    harness.on_prompt_input_bar_cancelled(PromptInputBar.Cancelled("text", "prompt"))

    assert len(harness.notifications) == 1
    message, _severity, title = harness.notifications[0]
    assert title == "Prompt input cancelled — saved to history"
    assert message.startswith('"longprompt longprompt')
    assert message.endswith('…"')


# --- keep_bar context lifecycle (the race the design calls out) ------------


def test_keep_bar_launch_clones_context_and_preserves_base() -> None:
    app = _FakeApp()
    base = app._prompt_context
    assert base is not None

    app._finish_agent_launch("pane one", keep_bar=True)

    # The bar is NOT unmounted and the base context is untouched.
    assert app.unmount_calls == []
    assert app._prompt_context is base
    assert base.timestamp == "ts"

    # The submitted payload carries an independent snapshot identity.
    assert len(app.launch_tasks) == 1
    task = app.launch_tasks[0]
    assert task["prompt"] == "pane one"
    extra = task["extra_payload"]
    assert extra is not None
    assert extra["workflow_name"] != base.workflow_name
    assert extra["workflow_name"].startswith("ace(run)-")
    assert extra["display_name"] == base.display_name


def test_keep_bar_launch_keeps_ctrl_space_gated() -> None:
    app = _KeepBarGateApp()

    app._finish_agent_launch("pane one", keep_bar=True)

    assert app.unmount_calls == []
    assert app._prompt_context is not None
    assert (
        check_app_action(app, "start_agent_from_patch", (), lambda *_args: True)
        is False
    )


def test_back_to_back_keep_bar_launches_use_distinct_contexts() -> None:
    app = _FakeApp()
    base = app._prompt_context

    app._finish_agent_launch("pane one", keep_bar=True)
    app._finish_agent_launch("pane two", keep_bar=True)

    assert app._prompt_context is base  # base never mutated
    assert [task["prompt"] for task in app.launch_tasks] == ["pane one", "pane two"]
    first, second = (task["extra_payload"] for task in app.launch_tasks)
    assert first is not None
    assert second is not None
    # Independent snapshots -> no cross-submit clobbering of launch identity.
    assert first["workflow_name"] != second["workflow_name"]


def test_keep_bar_false_launch_unmounts_like_today() -> None:
    app = _FakeApp()

    app._finish_agent_launch("solo prompt")

    assert app.unmount_calls == ["submit"]
    assert app._prompt_context is None
    assert len(app.launch_tasks) == 1
    assert app.launch_tasks[0]["prompt"] == "solo prompt"
