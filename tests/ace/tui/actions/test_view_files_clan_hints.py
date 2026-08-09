"""End-to-end coverage for the ``v`` flow on a synthetic clan container.

These drive the real clan hint render through the real view-hint action
mixins, so a break anywhere between ``build_clan_detail_text`` and the pager
handoff fails here rather than in a renderer-only unit test.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.hints._files import FileViewingMixin
from sase.ace.tui.actions.hints._processing import InputProcessingMixin
from sase.ace.tui.models._agent_clan_sections import (
    CLAN_DISK_SECTIONS,
    clan_section_member_rows,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets import HintInputBar
from sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation import (
    cache_clan_disk_snapshot,
    mark_clan_snapshot_loading,
    prepare_clan_section_snapshot,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import rich_clan_snapshot
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel


class _HintContainer:
    is_attached = True

    def __init__(self) -> None:
        self.mounted: list[object] = []

    def mount(self, widget: object) -> None:
        self.mounted.append(widget)


class _ClanViewApp(InputProcessingMixin, FileViewingMixin):
    """App double wiring the real hint mixins to a real clan detail panel."""

    def __init__(self, agent: Agent, detail: FakePromptPanel) -> None:
        self.agent = agent
        self.detail = detail
        self.container = _HintContainer()
        self.current_tab = "agents"
        self._hint_mode_active = False
        self._hint_mode_hints_for = None
        self._accept_mode_active = False
        self._rewind_mode_active = False
        self._hint_mappings: dict[int, str] = {}
        self._hint_tool_call_reports = {}
        self._hint_commit_views = {}
        self._hint_patch_name = ""
        self.notify = MagicMock()
        self._refresh_agents_display = MagicMock()
        self._view_files_with_pager = MagicMock()
        self._workers: list[asyncio.Task[object]] = []

    def _get_selected_agent(self) -> Agent:
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


def _clan_app(
    tmp_path: Path,
    *,
    enriched: bool,
) -> tuple[_ClanViewApp, str]:
    """Return a clan view app plus the path its summary hint should resolve to."""
    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(tmp_path)
    container.clan_summary = "Wrote the report to docs/clan_report.md"

    detail = FakePromptPanel()
    detail.app = SimpleNamespace(  # type: ignore[attr-defined]
        panel_fold_level=FoldLevel.COLLAPSED,
        _panel_fold_overrides=SimpleNamespace(snapshot=lambda: {}),
    )
    prepare_clan_section_snapshot(detail, container)
    if enriched:
        disk = snapshot.disk
        assert disk is not None
        assert cache_clan_disk_snapshot(detail, container, disk) is not None
    else:
        mark_clan_snapshot_loading(detail, container, CLAN_DISK_SECTIONS)

    return _ClanViewApp(container, detail), str(tmp_path / "docs" / "clan_report.md")


@pytest.mark.asyncio
async def test_clan_view_hint_submission_opens_the_summary_path(
    tmp_path: Path,
) -> None:
    app, expected = _clan_app(tmp_path, enriched=True)

    app._view_agent_files()
    assert isinstance(app.container.mounted[0], HintInputBar)

    for _ in range(8):
        await asyncio.sleep(0)
    assert app._hint_mappings == {1: expected}

    app.on_hint_input_bar_submitted(HintInputBar.Submitted("1", "view"))
    for _ in range(8):
        await asyncio.sleep(0)

    app._view_files_with_pager.assert_called_once_with([expected])
    app.notify.assert_not_called()


@pytest.mark.asyncio
async def test_clan_hint_submitted_during_enrichment_waits_for_mappings(
    tmp_path: Path,
) -> None:
    """Submitting mid-enrichment must wait on the readiness event, not fail."""
    app, expected = _clan_app(tmp_path, enriched=False)

    app._view_agent_files()
    assert app._hint_mappings == {}

    app.on_hint_input_bar_submitted(HintInputBar.Submitted("1", "view"))
    for _ in range(8):
        await asyncio.sleep(0)

    app._view_files_with_pager.assert_called_once_with([expected])
    app.notify.assert_not_called()
