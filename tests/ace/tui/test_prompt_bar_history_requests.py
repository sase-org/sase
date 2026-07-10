"""Tests for prompt history request handling from the prompt bar."""

from __future__ import annotations

from sase.ace.tui.actions.agent_workflow._prompt_bar_requests import (
    PromptBarRequestsMixin,
)
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.modals import (
    ConfirmActionModal,
    PromptHistoryAction,
    PromptHistoryResult,
)
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
        self.is_mounted = True

    def focus(self) -> None:
        self.focus_count += 1


class _Bar:
    def __init__(
        self,
        text_area: _TextArea,
        *,
        has_properties: bool = False,
        current_frontmatter: str = "",
        load_result: bool = True,
    ) -> None:
        self.text_area = text_area
        self.is_mounted = True
        self._has_properties = has_properties
        self._current_frontmatter = current_frontmatter
        self._load_result = load_result
        self.load_calls: list[tuple[object, str, str]] = []

    def active_text_area(self) -> _TextArea:
        return self.text_area

    def has_frontmatter_properties(self) -> bool:
        return self._has_properties

    def current_frontmatter(self) -> str:
        return self._current_frontmatter

    def load_prompt_into_pane(self, target: object, pane_id: str, text: str) -> bool:
        self.load_calls.append((target, pane_id, text))
        return self._load_result


class _HistoryRequestHarness(PromptBarRequestsMixin):
    def __init__(
        self,
        *,
        has_properties: bool = False,
        current_frontmatter: str = "",
        load_result: bool = True,
    ) -> None:
        self._prompt_context: PromptContext | None = _ctx()
        self.text_area = _TextArea()
        self.bar = _Bar(
            self.text_area,
            has_properties=has_properties,
            current_frontmatter=current_frontmatter,
            load_result=load_result,
        )
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


def _select_load(harness: _HistoryRequestHarness, prompt_text: str) -> None:
    """Open history and drive its callback with a ``LOAD`` selection."""
    event = PromptInputBar.HistoryRequested(preserve_prompt_bar=True)
    harness.on_prompt_input_bar_history_requested(event)
    _modal, history_cb = harness.pushed[0]
    history_cb(PromptHistoryResult(PromptHistoryAction.LOAD, prompt_text))


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


def test_load_without_conflict_calls_load_prompt_into_pane_once() -> None:
    harness = _HistoryRequestHarness()

    _select_load(harness, "loaded body")

    assert harness.bar.load_calls == [(harness.text_area, "", "loaded body")]
    # No confirmation modal was pushed on top of the history modal.
    assert len(harness.pushed) == 1
    assert harness.notifications == []
    assert harness.unmount_count == 0
    assert harness._prompt_context is not None


def test_load_with_frontmatter_conflict_confirms_before_load() -> None:
    harness = _HistoryRequestHarness(
        has_properties=True,
        current_frontmatter="---\ndescription: current\n---",
    )

    incoming = "---\ndescription: incoming\n---\nbody"
    _select_load(harness, incoming)

    # The load waits behind a confirmation modal.
    assert harness.bar.load_calls == []
    assert len(harness.pushed) == 2
    confirm_modal, confirm_cb = harness.pushed[1]
    assert isinstance(confirm_modal, ConfirmActionModal)

    # Confirming applies the load with the built text.
    confirm_cb(True)
    assert harness.bar.load_calls == [(harness.text_area, "", incoming)]
    assert harness.notifications == []


def test_load_conflict_declined_aborts_and_refocuses_origin() -> None:
    harness = _HistoryRequestHarness(
        has_properties=True,
        current_frontmatter="---\ndescription: current\n---",
    )

    _select_load(harness, "---\ndescription: incoming\n---\nbody")
    _confirm_modal, confirm_cb = harness.pushed[1]

    confirm_cb(False)

    # Nothing was loaded; the origin pane is refocused and the bar stays mounted.
    assert harness.bar.load_calls == []
    assert harness.text_area.focus_count == 1
    assert harness.unmount_count == 0
    assert harness._prompt_context is not None


def test_load_identical_frontmatter_skips_confirmation() -> None:
    same_fm = "---\ndescription: same\n---"
    harness = _HistoryRequestHarness(
        has_properties=True,
        current_frontmatter=same_fm,
    )

    incoming = f"{same_fm}\nbody"
    _select_load(harness, incoming)

    # A byte-identical overwrite is a no-op, so no confirmation is shown.
    assert len(harness.pushed) == 1
    assert harness.bar.load_calls == [(harness.text_area, "", incoming)]


def test_load_stale_pane_warns_without_unmount() -> None:
    harness = _HistoryRequestHarness(load_result=False)

    _select_load(harness, "loaded body")

    assert harness.bar.load_calls == [(harness.text_area, "", "loaded body")]
    assert harness.notifications == [
        ("Prompt pane is no longer available - selection discarded", "warning")
    ]
    assert harness.unmount_count == 0
    assert harness._prompt_context is not None
