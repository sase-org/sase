"""ACE TUI PNG visual snapshot coverage for the saved agent group revival modal.

ChangeSpecs-tab and footer snapshots live in ``test_ace_png_snapshots``.
Shared fixtures live in ``_ace_png_snapshot_helpers``.
"""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals.saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalModal,
)
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupPageWire,
    SavedAgentGroupRefWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03


async def test_saved_agent_group_modal_normal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    recent_groups = tuple(_recent_group_summary(idx) for idx in range(2))
    groups = tuple(_saved_group_summary(idx) for idx in range(3))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _push_saved_group_modal(
            page,
            SavedAgentGroupPageWire(groups=groups, next_cursor=None),
            {},
            recent_page=SavedAgentGroupPageWire(
                groups=recent_groups,
                next_cursor=None,
            ),
        )

        ace_png_visual.assert_page_png(
            page,
            "saved_agent_group_revival_normal_120x40",
            title="ACE saved agent group modal normal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_saved_agent_group_modal_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _push_saved_group_modal(
            page,
            SavedAgentGroupPageWire(groups=(), next_cursor=None),
            {},
        )

        ace_png_visual.assert_page_png(
            page,
            "saved_agent_group_revival_empty_120x40",
            title="ACE saved agent group modal empty",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_saved_agent_group_modal_load_more_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    groups = tuple(_saved_group_summary(idx) for idx in range(20))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = await _push_saved_group_modal(
            page,
            SavedAgentGroupPageWire(groups=groups, next_cursor=20),
            {},
        )
        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_list.highlighted = len(option_list.options) - 2
        modal._update_preview_for_option_id("load-more")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "saved_agent_group_revival_load_more_120x40",
            title="ACE saved agent group modal load more",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_saved_agent_group_modal_preview_rich_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    summary = _saved_group_summary(
        0,
        title="6 agents across 3 PRs",
        agent_count=6,
        top_level_agent_count=4,
        status_counts={"DONE": 3, "FAILED": 1, "RUNNING": 2},
        project_names=("sase", "sase-core"),
        cl_names=("backend", "frontend", "regression"),
    )
    group = _saved_group_from_summary(summary, ref_count=6)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _push_saved_group_modal(
            page,
            SavedAgentGroupPageWire(groups=(summary,), next_cursor=None),
            {summary.group_id: group},
        )

        ace_png_visual.assert_page_png(
            page,
            "saved_agent_group_revival_preview_rich_120x40",
            title="ACE saved agent group modal preview-rich",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def _push_saved_group_modal(
    page: AcePage,
    initial_page: SavedAgentGroupPageWire,
    groups_by_id: dict[str, SavedAgentGroupWire],
    *,
    recent_page: SavedAgentGroupPageWire | None = None,
) -> SavedAgentGroupRevivalModal:
    modal = SavedAgentGroupRevivalModal(
        initial_page,
        recent_page=recent_page,
        group_loader=groups_by_id.get,
    )
    page.app.push_screen(modal)
    await page.expect_modal("SavedAgentGroupRevivalModal")
    await wait_for_visual_idle(page)
    return modal


def _saved_group_summary(
    idx: int,
    *,
    title: str = "3 agents from @visual",
    agent_count: int = 3,
    top_level_agent_count: int = 2,
    status_counts: dict[str, int] | None = None,
    project_names: tuple[str, ...] = ("sase",),
    cl_names: tuple[str, ...] = ("visual-polish",),
) -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id=f"visual-group-{idx:02}",
        created_at=f"May 27 12:{idx:02}",
        source="marked_agents",
        title=title,
        agent_count=agent_count,
        top_level_agent_count=top_level_agent_count,
        status_counts=status_counts or {"DONE": 2, "FAILED": 1},
        project_names=project_names,
        cl_names=cl_names,
    )


def _recent_group_summary(idx: int) -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id=f"recent-visual-group-{idx:02}",
        created_at=f"May 27 12:{idx + 30:02}",
        source="recent_dismissal",
        title="2 agents from @visual",
        agent_count=2,
        top_level_agent_count=2,
        status_counts={"DONE": 2},
        project_names=("sase",),
        cl_names=("visual-polish",),
    )


def _saved_group_from_summary(
    summary: SavedAgentGroupSummaryWire,
    *,
    ref_count: int,
) -> SavedAgentGroupWire:
    refs = tuple(
        SavedAgentGroupRefWire(
            agent_type="run",
            cl_name=("backend", "frontend", "regression")[idx % 3],
            raw_suffix=f"20260527120{idx:02}",
            display_name=f"visual-worker-{idx + 1}",
            agent_name=f"visual.agent.{idx + 1}",
            status=("DONE", "RUNNING", "FAILED")[idx % 3],
            model=("gpt-5", "opus", "flash")[idx % 3],
            llm_provider=("codex", "claude", "gemini")[idx % 3],
        )
        for idx in range(ref_count)
    )
    return SavedAgentGroupWire(
        group_id=summary.group_id,
        created_at=summary.created_at,
        source=summary.source,
        title=summary.title,
        agent_count=summary.agent_count,
        top_level_agent_count=summary.top_level_agent_count,
        status_counts=summary.status_counts,
        project_names=summary.project_names,
        cl_names=summary.cl_names,
        agent_refs=refs,
    )
