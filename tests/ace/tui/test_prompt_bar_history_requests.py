"""Tests for prompt history request handling from the prompt bar.

History opens the complete Prompts overlay on the History tab (with this
entry point's seed/filter/scope as the live-bar origin); the tests drive
the overlay result callback with History-tab outcomes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sase.ace.tui.actions.agent_workflow._prompt_bar_requests import (
    PromptBarRequestsMixin,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_stash_restore import (
    PromptBarStashRestoreMixin,
)
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.modals import (
    ConfirmActionModal,
    PromptHistoryAction,
    PromptHistoryResult,
)
from sase.ace.tui.modals.prompts_modal import (
    PromptsModal,
    PromptsOrigin,
    PromptsResult,
    PromptsTab,
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


class _HistoryRequestHarness(PromptBarRequestsMixin, PromptBarStashRestoreMixin):
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

    def _mounted_prompt_bar(self) -> _Bar:  # type: ignore[override]
        return self.bar

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _unmount_prompt_bar(self) -> None:
        self.unmount_count += 1


async def _wait_tasks(harness: _HistoryRequestHarness) -> None:
    tasks = list(getattr(harness, "_prompt_stash_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path)


async def _open_history(
    harness: _HistoryRequestHarness, event: object
) -> tuple[PromptsModal, object]:
    """Open history through the overlay and return the modal + callback."""
    from tests.ace.tui.actions._prompt_stash_restore_helpers import (
        _skip_without_lifecycle_bindings,
    )

    # History opens through the overlay funnel, whose lifecycle snapshot
    # read fails closed without the Rust trash-lifecycle bindings.
    _skip_without_lifecycle_bindings()
    harness.on_prompt_input_bar_history_requested(event)
    await _wait_tasks(harness)
    assert len(harness.pushed) == 1
    modal, overlay_cb = harness.pushed[0]
    assert isinstance(modal, PromptsModal)
    assert modal._active_tab is PromptsTab.HISTORY
    return modal, overlay_cb


def _history_outcome(action: PromptHistoryAction, prompt_text: str) -> PromptsResult:
    return PromptsResult(
        tab=PromptsTab.HISTORY,
        origin=PromptsOrigin(kind="live_bar"),
        history=PromptHistoryResult(action, prompt_text),
    )


async def _select_load(
    harness: _HistoryRequestHarness, prompt_text: str
) -> tuple[PromptsModal, object]:
    """Open history and drive its callback with a ``LOAD`` selection."""
    event = PromptInputBar.HistoryRequested(preserve_prompt_bar=True)
    modal, overlay_cb = await _open_history(harness, event)
    overlay_cb(_history_outcome(PromptHistoryAction.LOAD, prompt_text))  # type: ignore[operator]
    return modal, overlay_cb


async def test_ctrl_k_history_cancel_refocuses_prompt_bar_without_unmounting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    harness = _HistoryRequestHarness()
    event = PromptInputBar.HistoryRequested(
        initial_filter="draft prompt",
        preserve_prompt_bar=True,
    )

    modal, overlay_cb = await _open_history(harness, event)
    overlay_cb(None)  # type: ignore[operator]

    assert modal._origin.initial_filter == "draft prompt"
    assert harness.text_area.focus_count == 1
    assert harness.unmount_count == 0
    assert harness.notifications == []
    assert harness._prompt_context is not None


async def test_prompt_seed_routes_to_the_modal_unscoped_from_initial_filter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    harness = _HistoryRequestHarness()
    event = PromptInputBar.HistoryRequested(
        preserve_prompt_bar=True,
        prompt_seed="#gh:sase fix parser",
    )

    modal, _overlay_cb = await _open_history(harness, event)

    assert modal._origin.prompt_seed == "#gh:sase fix parser"
    assert modal._origin.initial_filter == ""


async def test_leader_open_history_stays_unscoped_with_no_seed_or_filter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    harness = _HistoryRequestHarness()
    event = PromptInputBar.HistoryRequested(preserve_prompt_bar=True)

    modal, _overlay_cb = await _open_history(harness, event)

    assert modal._origin.prompt_seed is None
    assert modal._origin.initial_filter == ""


async def test_load_without_conflict_calls_load_prompt_into_pane_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    harness = _HistoryRequestHarness()

    await _select_load(harness, "loaded body")

    assert harness.bar.load_calls == [(harness.text_area, "", "loaded body")]
    # No confirmation modal was pushed on top of the history modal.
    assert len(harness.pushed) == 1
    assert harness.notifications == []
    assert harness.unmount_count == 0
    assert harness._prompt_context is not None


async def test_load_with_frontmatter_conflict_confirms_before_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    harness = _HistoryRequestHarness(
        has_properties=True,
        current_frontmatter="---\ndescription: current\n---",
    )

    incoming = "---\ndescription: incoming\n---\nbody"
    await _select_load(harness, incoming)

    # The load waits behind a confirmation modal.
    assert harness.bar.load_calls == []
    assert len(harness.pushed) == 2
    confirm_modal, confirm_cb = harness.pushed[1]
    assert isinstance(confirm_modal, ConfirmActionModal)

    # Confirming applies the load with the built text.
    confirm_cb(True)
    assert harness.bar.load_calls == [(harness.text_area, "", incoming)]
    assert harness.notifications == []


async def test_load_conflict_declined_aborts_and_refocuses_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    harness = _HistoryRequestHarness(
        has_properties=True,
        current_frontmatter="---\ndescription: current\n---",
    )

    await _select_load(harness, "---\ndescription: incoming\n---\nbody")
    _confirm_modal, confirm_cb = harness.pushed[1]

    confirm_cb(False)

    # Nothing was loaded; the origin pane is refocused and the bar stays mounted.
    assert harness.bar.load_calls == []
    assert harness.text_area.focus_count == 1
    assert harness.unmount_count == 0
    assert harness._prompt_context is not None


async def test_load_identical_frontmatter_skips_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    same_fm = "---\ndescription: same\n---"
    harness = _HistoryRequestHarness(
        has_properties=True,
        current_frontmatter=same_fm,
    )

    incoming = f"{same_fm}\nbody"
    await _select_load(harness, incoming)

    # A byte-identical overwrite is a no-op, so no confirmation is shown.
    assert len(harness.pushed) == 1
    assert harness.bar.load_calls == [(harness.text_area, "", incoming)]


async def test_load_stale_pane_warns_without_unmount(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_store_at(monkeypatch, tmp_path / "prompt_stash.jsonl")
    harness = _HistoryRequestHarness(load_result=False)

    await _select_load(harness, "loaded body")

    assert harness.bar.load_calls == [(harness.text_area, "", "loaded body")]
    assert harness.notifications == [
        ("Prompt pane is no longer available - selection discarded", "warning")
    ]
    assert harness.unmount_count == 0
    assert harness._prompt_context is not None
