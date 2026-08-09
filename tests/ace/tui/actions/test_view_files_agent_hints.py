"""Tests for rendering and submitting agent view-file hints."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.hints._files import FileViewingMixin
from sase.ace.tui.actions.hints._processing import InputProcessingMixin
from sase.ace.tui.widgets import HintInputBar
from sase.ace.tui.widgets.prompt_panel._agent_display_state import AgentHintRender


class _PendingHintContainer:
    is_attached = True

    def __init__(self) -> None:
        self.mounted: list[object] = []

    def mount(self, widget: object) -> None:
        self.mounted.append(widget)


class _PendingAgentDetail:
    def __init__(self) -> None:
        self.update_calls = 0

    def update_display_with_hints(self, _agent: object) -> AgentHintRender:
        self.update_calls += 1
        return AgentHintRender(
            file_hints={},
            tool_call_reports={},
            header_enrichment_pending=True,
        )


class _ReadyFamilyAgentDetail:
    def __init__(self) -> None:
        self.update_calls = 0

    def update_display_with_hints(self, _agent: object) -> AgentHintRender:
        self.update_calls += 1
        return AgentHintRender(
            file_hints={1: "/tmp/family-report.txt"},
            tool_call_reports={},
        )


class _EmptyAgentDetail:
    def __init__(self) -> None:
        self.update_calls = 0

    def update_display_with_hints(self, _agent: object) -> AgentHintRender:
        self.update_calls += 1
        return AgentHintRender(file_hints={}, tool_call_reports={})


class _PendingAgentViewApp(FileViewingMixin):
    def __init__(self) -> None:
        self.agent = SimpleNamespace(
            cl_name="pending-agent",
            identity=("pending-agent",),
            is_family_container_row=False,
        )
        self.detail = _PendingAgentDetail()
        self.container = _PendingHintContainer()
        self.current_tab = "agents"
        self._hint_mode_active = False
        self._hint_mode_hints_for = None
        self._hint_mappings = {}
        self._hint_tool_call_reports = {}
        self._hint_commit_views = {}
        self.notify = MagicMock()
        self._refresh_agents_display = MagicMock()

    def _refocus_existing_hint_bar(self) -> bool:
        return False

    def _get_selected_agent(self) -> object:
        return self.agent

    def _remove_hint_input_bar(self) -> None:
        self._cancel_agent_hint_render_tasks()
        self._hint_mode_active = False
        self.container.mounted.clear()
        self._refresh_agents_display()

    def query_one(self, selector: str, _type: object = None) -> object:
        del _type
        if selector == "#agent-detail-panel":
            return self.detail
        if selector == "#agent-detail-container":
            return self.container
        raise AssertionError(selector)


@pytest.mark.asyncio
async def test_cold_agent_hint_render_keeps_view_mode_open_for_enrichment() -> None:
    app = _PendingAgentViewApp()

    app._view_agent_files()

    assert len(app.container.mounted) == 1
    assert app.detail.update_calls == 0
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    app.notify.assert_not_called()
    app._refresh_agents_display.assert_not_called()
    assert app._hint_mode_active
    assert app._hint_patch_name == "pending-agent"
    assert len(app.container.mounted) == 1
    assert isinstance(app.container.mounted[0], HintInputBar)


@pytest.mark.asyncio
async def test_family_with_displayed_artifact_mounts_view_hint_input() -> None:
    app = _PendingAgentViewApp()
    app.agent = SimpleNamespace(
        cl_name="family",
        identity=("family",),
        is_family_container_row=True,
    )
    app.detail = _ReadyFamilyAgentDetail()

    app._view_agent_files()

    assert len(app.container.mounted) == 1
    assert app.detail.update_calls == 0
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    app.notify.assert_not_called()
    app._refresh_agents_display.assert_not_called()
    assert app._hint_mappings == {1: "/tmp/family-report.txt"}
    assert len(app.container.mounted) == 1
    assert isinstance(app.container.mounted[0], HintInputBar)


@pytest.mark.asyncio
async def test_clan_with_summary_path_mounts_hint_input_without_warning() -> None:
    app = _PendingAgentViewApp()
    app.agent = SimpleNamespace(
        cl_name="research",
        identity=("research", "clan"),
        is_family_container_row=False,
        is_clan_container=True,
    )
    app.detail = _ReadyFamilyAgentDetail()

    app._view_agent_files()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    app.notify.assert_not_called()
    assert app._hint_mappings == {1: "/tmp/family-report.txt"}
    assert app._hint_mode_active
    assert len(app.container.mounted) == 1
    assert isinstance(app.container.mounted[0], HintInputBar)


@pytest.mark.asyncio
async def test_ordinary_agent_empty_hint_render_keeps_warning_behavior() -> None:
    app = _PendingAgentViewApp()
    app.detail = _EmptyAgentDetail()

    app._view_agent_files()

    assert len(app.container.mounted) == 1
    assert app.detail.update_calls == 0
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    app.notify.assert_called_once_with(
        "No files or commits found in agent details",
        severity="warning",
    )
    app._refresh_agents_display.assert_called_once_with()
    assert not app._hint_mode_active
    assert app.container.mounted == []


class _ImmediateSubmitAgentViewApp(InputProcessingMixin, FileViewingMixin):
    def __init__(self) -> None:
        self.agent = SimpleNamespace(
            cl_name="immediate-submit",
            identity=("immediate-submit",),
            is_family_container_row=False,
        )
        self.detail = _ReadyFamilyAgentDetail()
        self.container = _PendingHintContainer()
        self.current_tab = "agents"
        self._hint_mode_active = False
        self._hint_mode_hints_for = None
        self._accept_mode_active = False
        self._rewind_mode_active = False
        self._hint_mappings = {}
        self._hint_tool_call_reports = {}
        self._hint_commit_views = {}
        self._hint_patch_name = ""
        self.notify = MagicMock()
        self._refresh_agents_display = MagicMock()
        self._view_files_with_pager = MagicMock()
        self._workers: list[asyncio.Task[object]] = []

    def _get_selected_agent(self) -> object:
        return self.agent

    def _refocus_existing_hint_bar(self) -> bool:
        return False

    def query_one(self, selector: str, _type: object = None) -> object:
        del _type
        if selector == "#agent-detail-panel":
            return self.detail
        if selector == "#agent-detail-container":
            return self.container
        raise AssertionError(selector)

    def _remove_hint_input_bar(self, *, refresh: bool = True) -> None:
        del refresh
        self._cancel_agent_hint_render_tasks()
        self._hint_mode_active = False
        self.container.mounted.clear()

    def run_worker(self, work: object, **_kwargs: object) -> asyncio.Task[object]:
        task = asyncio.create_task(work)  # type: ignore[arg-type]
        self._workers.append(task)
        return task


@pytest.mark.asyncio
async def test_immediate_agent_hint_submission_waits_for_rendered_mapping() -> None:
    app = _ImmediateSubmitAgentViewApp()

    app._view_agent_files()
    assert app.detail.update_calls == 0
    assert app._hint_mappings == {}

    app.on_hint_input_bar_submitted(HintInputBar.Submitted("1", "view"))

    for _ in range(8):
        await asyncio.sleep(0)

    app._view_files_with_pager.assert_called_once_with(["/tmp/family-report.txt"])
    app.notify.assert_not_called()
