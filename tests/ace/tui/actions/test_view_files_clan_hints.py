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
from rich.text import Text

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
    build_clan_disk_snapshot,
    cache_clan_disk_snapshot,
    mark_clan_snapshot_loading,
    prepare_clan_section_snapshot,
)
from sase.scripts.sase_clan_summary_epic import _render_plan_summary
from sase.sdd._plan_display_models import PlanProvenanceSection
from sase.sdd.plan_display import PlanDisplay
from sase.sdd.plan_header_block import PlanHeaderSectionKind
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
async def test_clan_view_hint_parent_plan_uses_logical_plan_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plans_store = tmp_path / "plans-store" / "202608"
    plans_store.mkdir(parents=True)
    child_path = plans_store / "child.md"
    parent_path = plans_store / "parent.md"
    child_path.write_text("child\n", encoding="utf-8")
    parent_path.write_text("parent\n", encoding="utf-8")

    container, snapshot = rich_clan_snapshot()
    member = clan_section_member_rows(container)[0]
    member.workspace_dir = str(workspace)
    member.workspace_num = 7
    container.clan_summary = _render_plan_summary(
        "sase-parent",
        PlanDisplay(
            title="Child plan",
            goal="Keep parent plan hints resolvable.",
            authored_tier="tale",
            effective_tier="tale",
            actual_path=str(child_path),
            display_path="plan:202608/child.md",
            committed=True,
            exists=True,
            readable=True,
            frontmatter_readable=True,
            phase_availability="not-applicable",
            phases=(),
            validation_ok=True,
            size="small",
            provenance=(
                PlanProvenanceSection(
                    kind=PlanHeaderSectionKind.PARENT,
                    entries=("202608/parent.md",),
                    targets=("https://example.invalid/202608/parent.md",),
                ),
            ),
        ),
    )
    assert (
        " Parent: plan:202608/parent.md"
        in Text.from_markup(container.clan_summary).plain
    )

    base_disk = snapshot.disk
    assert base_disk is not None
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation."
        "build_agent_group_disk_snapshot",
        lambda *_args, **_kwargs: base_disk,
    )
    monkeypatch.setattr(
        "sase.sdd.plan_refs.parse_plan_reference",
        lambda value: SimpleNamespace(path=value.split(":", 1)[1]),
    )

    resolved_by_ref = {
        "plan:202608/child.md": child_path,
        "plan:202608/parent.md": parent_path,
    }

    def resolve_reference(
        value: str,
        *,
        workspace_dir: str,
        workspace_num: int,
    ) -> SimpleNamespace:
        assert workspace_dir == str(workspace)
        assert workspace_num == 7
        return SimpleNamespace(resolved_path=resolved_by_ref[value])

    resolve = MagicMock(side_effect=resolve_reference)
    monkeypatch.setattr("sase.sdd.plan_refs.resolve_plan_reference", resolve)

    detail = FakePromptPanel()
    detail.app = SimpleNamespace(  # type: ignore[attr-defined]
        panel_fold_level=FoldLevel.COLLAPSED,
        _panel_fold_overrides=SimpleNamespace(snapshot=lambda: {}),
    )
    prepared = prepare_clan_section_snapshot(detail, container)
    enriched_disk = build_clan_disk_snapshot(
        detail,
        container,
        prepared.in_memory,
        sections=CLAN_DISK_SECTIONS,
    )
    assert enriched_disk.hint_paths["plan:202608/parent.md"] == str(parent_path)
    assert enriched_disk.hint_paths["202608/parent.md"] == str(parent_path)
    assert cache_clan_disk_snapshot(detail, container, enriched_disk) is not None

    app = _ClanViewApp(container, detail)
    app._view_agent_files()
    assert isinstance(app.container.mounted[0], HintInputBar)

    for _ in range(8):
        await asyncio.sleep(0)

    fallback = workspace / "202608" / "parent.md"
    parent_hint = next(
        hint
        for hint, target in app._hint_mappings.items()
        if target == str(parent_path)
    )
    assert app._hint_mappings[parent_hint] == str(parent_path)
    assert str(fallback) not in app._hint_mappings.values()

    app.on_hint_input_bar_submitted(HintInputBar.Submitted(str(parent_hint), "view"))
    for _ in range(8):
        await asyncio.sleep(0)

    app._view_files_with_pager.assert_called_once_with([str(parent_path)])
    app.notify.assert_not_called()
    resolve.assert_any_call(
        "plan:202608/child.md",
        workspace_dir=str(workspace),
        workspace_num=7,
    )
    resolve.assert_any_call(
        "plan:202608/parent.md",
        workspace_dir=str(workspace),
        workspace_num=7,
    )


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
