"""Tests for the prompt-bar editor-return handlers.

The prompt editor key: on a single-pane bar it posts
:class:`EditorRequested` (legacy behavior: a ` @` review marker reloads the
whole bar, otherwise the edited text launches); on a multi-pane stack it posts
:class:`AllEditorRequested`, opening the whole stack as xprompt markdown and
reloading the edited result without launching.

The ``EditorRequested`` handler still carries a defensive stacked-bar branch
(edit only the active pane, never launch) for any programmatic caller that posts
that message while the bar holds multiple panes; the keymap no longer reaches it.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agent_workflow._prompt_bar_requests import (
    PromptBarRequestsMixin,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_mount import PromptBarMountMixin
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


class _FakeTextArea:
    def __init__(self) -> None:
        self.focus_calls = 0

    def focus(self) -> None:
        self.focus_calls += 1


class _FakeBar:
    def __init__(
        self, *, stacked: bool, markdown: str = "alpha\n\n---\n\nbeta"
    ) -> None:
        self._stacked = stacked
        self._markdown = markdown
        self.updated_panes: list[str] = []
        self.loaded_markdown: list[str] = []
        self.loaded_preserve_target: list[bool] = []
        self._text_area = _FakeTextArea()

    def is_stacked(self) -> bool:
        return self._stacked

    def update_active_pane(self, text: str) -> None:
        self.updated_panes.append(text)

    def xprompt_markdown_for_editor(self) -> str:
        return self._markdown

    def load_stack_from_xprompt_markdown(
        self, text: str, *, preserve_target: bool = False
    ) -> None:
        self.loaded_markdown.append(text)
        self.loaded_preserve_target.append(preserve_target)

    def active_text_area(self) -> _FakeTextArea:
        return self._text_area


class _EditorHarness(PromptBarRequestsMixin):
    """Drive ``on_prompt_input_bar_editor_requested`` without a live DOM."""

    def __init__(self, *, bar: _FakeBar | None, editor_result: str | None) -> None:
        self._prompt_context: PromptContext | None = _ctx()
        self._bar = bar
        self._editor_result = editor_result
        self.finished: list[str] = []
        self.loaded: list[str] = []
        self.unmount_calls = 0
        self.notifications: list[tuple[str, str | None]] = []
        self.editor_inputs: list[str] = []

    def query_one(self, selector: str, expect_type: Any = None) -> Any:
        del selector, expect_type
        if self._bar is None:
            raise RuntimeError("no prompt bar")
        return self._bar

    def _open_editor_for_agent_prompt(
        self, content: str = "", cursor_row: int = 0, cursor_col: int = 0
    ) -> str | None:
        del cursor_row, cursor_col
        self.editor_inputs.append(content)
        return self._editor_result

    def _finish_agent_launch(self, prompt: str, *, keep_bar: bool = False) -> None:
        del keep_bar
        self.finished.append(prompt)

    def _load_editor_markdown_into_bar(self, prompt: str) -> None:
        self.loaded.append(prompt)

    def _unmount_prompt_bar(self) -> None:
        self.unmount_calls += 1

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))


class _MountHarness(PromptBarMountMixin):
    def __init__(self, bar: _FakeBar | None) -> None:
        self._bar = bar
        self._prompt_context: PromptContext | None = _ctx()

    def query_one(self, selector: str, expect_type: Any = None) -> Any:
        del selector, expect_type
        if self._bar is None:
            raise RuntimeError("no prompt bar")
        return self._bar


def _event(text: str = "second") -> PromptInputBar.EditorRequested:
    return PromptInputBar.EditorRequested(current_text=text)


def _all_event() -> PromptInputBar.AllEditorRequested:
    return PromptInputBar.AllEditorRequested()


# --- defensive: programmatic EditorRequested on a multi-pane stack ---------
# The prompt editor keymap posts AllEditorRequested when stacked (see the
# all-editor tests below); these cover the handler's defensive branch for a
# programmatic caller
# that posts EditorRequested while the bar holds multiple panes -- it edits only
# the active pane and never launches.


def test_stacked_editor_return_updates_active_pane_without_launching() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result="second EDITED")

    harness.on_prompt_input_bar_editor_requested(_event())

    assert bar.updated_panes == ["second EDITED"]
    assert harness.finished == []
    assert harness.loaded == []
    assert harness.unmount_calls == 0
    assert harness._prompt_context is not None


def test_stacked_editor_return_strips_review_marker_into_pane() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result="second EDITED @")

    harness.on_prompt_input_bar_editor_requested(_event())

    # The ` @` review marker is stripped; the cleaned text lands in the pane.
    assert bar.updated_panes == ["second EDITED"]
    assert harness.finished == []
    assert harness.unmount_calls == 0


def test_stacked_editor_empty_return_keeps_stack_and_refocuses() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result=None)

    harness.on_prompt_input_bar_editor_requested(_event())

    assert bar.updated_panes == []
    assert bar.active_text_area().focus_calls == 1
    assert harness.unmount_calls == 0
    assert harness._prompt_context is not None
    assert harness.notifications == []


# --- single pane: legacy behavior is preserved -----------------------------


def test_single_pane_editor_return_launches_as_before() -> None:
    bar = _FakeBar(stacked=False)
    harness = _EditorHarness(bar=bar, editor_result="edited prompt")

    harness.on_prompt_input_bar_editor_requested(_event())

    assert harness.finished == ["edited prompt"]
    assert bar.updated_panes == []
    assert harness.unmount_calls == 0


def test_single_pane_editor_review_marker_reloads_whole_bar() -> None:
    bar = _FakeBar(stacked=False)
    harness = _EditorHarness(bar=bar, editor_result="keep editing @")

    harness.on_prompt_input_bar_editor_requested(_event())

    assert harness.loaded == ["keep editing"]
    assert harness.finished == []
    assert bar.updated_panes == []


def test_single_pane_editor_review_marker_reloads_multi_agent_markdown() -> None:
    # A ` @` review marker on a single-pane bar returning multi-agent markdown
    # with leading xprompt frontmatter reloads through the editor-markdown
    # (xprompt) path — the cleaned buffer keeps its frontmatter + ``---``
    # separators so the bar lifts the frontmatter and splits into panes — and
    # never launches. The marker on the last body line drives the whole reload.
    bar = _FakeBar(stacked=False)
    editor_result = (
        "---\n"
        "description: Review auth and API separately\n"
        "xprompts:\n"
        "  _shared: Use the same style guide.\n"
        "---\n"
        "Review auth.\n"
        "---\n"
        "Review API. @"
    )
    harness = _EditorHarness(bar=bar, editor_result=editor_result)

    harness.on_prompt_input_bar_editor_requested(_event())

    assert harness.loaded == [
        "---\n"
        "description: Review auth and API separately\n"
        "xprompts:\n"
        "  _shared: Use the same style guide.\n"
        "---\n"
        "Review auth.\n"
        "---\n"
        "Review API."
    ]
    assert harness.finished == []
    assert bar.updated_panes == []
    assert harness.unmount_calls == 0


def test_load_editor_markdown_into_bar_preserves_target() -> None:
    bar = _FakeBar(stacked=False)
    harness = _MountHarness(bar)

    harness._load_editor_markdown_into_bar("edited\n---\nstack")

    assert bar.loaded_markdown == ["edited\n---\nstack"]
    assert bar.loaded_preserve_target == [True]


def test_single_pane_editor_empty_return_unmounts() -> None:
    bar = _FakeBar(stacked=False)
    harness = _EditorHarness(bar=bar, editor_result=None)

    harness.on_prompt_input_bar_editor_requested(_event())

    assert harness.unmount_calls == 1
    assert harness._prompt_context is None
    assert harness.notifications == [("No prompt from editor - cancelled", "warning")]


# --- prompt editor keymap on a multi-pane stack edits the whole stack -------


def test_all_editor_opens_whole_stack_not_active_pane() -> None:
    bar = _FakeBar(stacked=True, markdown="alpha\n\n---\n\nbeta")
    harness = _EditorHarness(bar=bar, editor_result="alpha\n---\nbeta EDITED")

    harness.on_prompt_input_bar_all_editor_requested(_all_event())

    # The editor opens the spaced whole-stack markdown, never the active pane
    # alone; the edited result reloads verbatim (compact separators preserved).
    assert harness.editor_inputs == ["alpha\n\n---\n\nbeta"]
    assert bar.loaded_markdown == ["alpha\n---\nbeta EDITED"]
    assert bar.loaded_preserve_target == [True]
    assert bar.updated_panes == []


def test_all_editor_nonempty_return_reloads_without_launching() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result="uno\n---\ndos")

    harness.on_prompt_input_bar_all_editor_requested(_all_event())

    # All-stack editor reloads the bar; it never launches or unmounts.
    assert bar.loaded_markdown == ["uno\n---\ndos"]
    assert bar.loaded_preserve_target == [True]
    assert harness.finished == []
    assert harness.loaded == []
    assert harness.unmount_calls == 0
    assert harness._prompt_context is not None


def test_all_editor_strips_review_marker_on_reload() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result="uno\n---\ndos @")

    harness.on_prompt_input_bar_all_editor_requested(_all_event())

    # The ` @` review marker is stripped before the markdown is re-stacked.
    assert bar.loaded_markdown == ["uno\n---\ndos"]
    assert bar.loaded_preserve_target == [True]
    assert harness.finished == []


def test_all_editor_empty_return_keeps_bar_and_refocuses() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result=None)

    harness.on_prompt_input_bar_all_editor_requested(_all_event())

    assert bar.loaded_markdown == []
    assert bar.active_text_area().focus_calls == 1
    assert harness.unmount_calls == 0
    assert harness._prompt_context is not None
    assert harness.notifications == []


def test_all_editor_noop_without_prompt_context() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result="anything")
    harness._prompt_context = None

    harness.on_prompt_input_bar_all_editor_requested(_all_event())

    assert harness.editor_inputs == []
    assert bar.loaded_markdown == []
