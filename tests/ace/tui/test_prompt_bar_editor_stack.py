"""Phase 5 tests: ``^G`` edits the active pane of a multi-pane prompt stack.

The editor-return handler must distinguish a single-pane bar (legacy behavior:
``%edit`` reloads the whole bar, otherwise the edited text launches) from a
multi-pane stack, where ``^G`` edits only the selected pane: the result is
loaded back into that pane and the rest of the stack — and its mounted bar — is
left untouched, never launched.
"""

from __future__ import annotations

from typing import Any

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


class _FakeTextArea:
    def __init__(self) -> None:
        self.focus_calls = 0

    def focus(self) -> None:
        self.focus_calls += 1


class _FakeBar:
    def __init__(self, *, stacked: bool, markdown: str = "alpha\n---\nbeta") -> None:
        self._stacked = stacked
        self._markdown = markdown
        self.updated_panes: list[str] = []
        self.loaded_markdown: list[str] = []
        self._text_area = _FakeTextArea()

    def is_stacked(self) -> bool:
        return self._stacked

    def update_active_pane(self, text: str) -> None:
        self.updated_panes.append(text)

    def xprompt_markdown_for_editor(self) -> str:
        return self._markdown

    def load_stack_from_xprompt_markdown(self, text: str) -> None:
        self.loaded_markdown.append(text)

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

    def _load_prompt_into_bar(self, prompt: str) -> None:
        self.loaded.append(prompt)

    def _unmount_prompt_bar(self) -> None:
        self.unmount_calls += 1

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))


def _event(text: str = "second") -> PromptInputBar.EditorRequested:
    return PromptInputBar.EditorRequested(current_text=text)


def _all_event() -> PromptInputBar.AllEditorRequested:
    return PromptInputBar.AllEditorRequested()


# --- multi-pane stack: ^G edits the active pane ----------------------------


def test_stacked_editor_return_updates_active_pane_without_launching() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result="second EDITED")

    harness.on_prompt_input_bar_editor_requested(_event())

    assert bar.updated_panes == ["second EDITED"]
    assert harness.finished == []
    assert harness.loaded == []
    assert harness.unmount_calls == 0
    assert harness._prompt_context is not None


def test_stacked_editor_return_strips_edit_directive_into_pane() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result="%edit\nsecond EDITED")

    harness.on_prompt_input_bar_editor_requested(_event())

    # The ``%edit`` directive is stripped; the cleaned text lands in the pane.
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


def test_single_pane_editor_edit_directive_reloads_whole_bar() -> None:
    bar = _FakeBar(stacked=False)
    harness = _EditorHarness(bar=bar, editor_result="%edit\nkeep editing")

    harness.on_prompt_input_bar_editor_requested(_event())

    assert harness.loaded == ["keep editing"]
    assert harness.finished == []
    assert bar.updated_panes == []


def test_single_pane_editor_empty_return_unmounts() -> None:
    bar = _FakeBar(stacked=False)
    harness = _EditorHarness(bar=bar, editor_result=None)

    harness.on_prompt_input_bar_editor_requested(_event())

    assert harness.unmount_calls == 1
    assert harness._prompt_context is None
    assert harness.notifications == [("No prompt from editor - cancelled", "warning")]


# --- ^⇧G edits the whole stack (all-editor) --------------------------------


def test_all_editor_opens_whole_stack_not_active_pane() -> None:
    bar = _FakeBar(stacked=True, markdown="alpha\n---\nbeta")
    harness = _EditorHarness(bar=bar, editor_result="alpha\n---\nbeta EDITED")

    harness.on_prompt_input_bar_all_editor_requested(_all_event())

    # The editor opens the joined stack markdown, never the active pane alone.
    assert harness.editor_inputs == ["alpha\n---\nbeta"]
    assert bar.loaded_markdown == ["alpha\n---\nbeta EDITED"]
    assert bar.updated_panes == []


def test_all_editor_nonempty_return_reloads_without_launching() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result="uno\n---\ndos")

    harness.on_prompt_input_bar_all_editor_requested(_all_event())

    # All-stack editor reloads the bar; it never launches or unmounts.
    assert bar.loaded_markdown == ["uno\n---\ndos"]
    assert harness.finished == []
    assert harness.loaded == []
    assert harness.unmount_calls == 0
    assert harness._prompt_context is not None


def test_all_editor_strips_edit_directive_on_reload() -> None:
    bar = _FakeBar(stacked=True)
    harness = _EditorHarness(bar=bar, editor_result="%edit\nuno\n---\ndos")

    harness.on_prompt_input_bar_all_editor_requested(_all_event())

    # The ``%edit`` directive is stripped before the markdown is re-stacked.
    assert bar.loaded_markdown == ["uno\n---\ndos"]
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
