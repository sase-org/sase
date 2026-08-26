"""Mounted integration tests for Agents-tab fold mode."""

from datetime import datetime
from pathlib import Path

import pytest

from textual.containers import VerticalScroll
from textual.geometry import Region

from sase.ace.testing import AcePage
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel, cycle_forward
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation import (
    get_cached_clan_section_snapshot,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)


def _mounted_clan_agents(tmp_path: Path) -> list[Agent]:
    artifacts = tmp_path / "phase-artifacts"
    artifacts.mkdir()
    (artifacts / "raw_xprompt.md").write_text(
        "#review mounted clan segment\n",
        encoding="utf-8",
    )
    (artifacts / "01_prompt.md").write_text(
        "Exercise every fold chord.\n",
        encoding="utf-8",
    )
    response = artifacts / "response.md"
    response.write_text("Mounted clan reply.\n", encoding="utf-8")
    generation = "20260718120000"
    phase = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="mounted-phase",
        project_file="/tmp/mounted.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 18, 12, 0, 0),
        stop_time=datetime(2026, 7, 18, 12, 3, 0),
        raw_suffix="20260718120000-phase",
        agent_name="sase-mounted.phase",
        agent_clan="sase-mounted",
        agent_clan_generation=generation,
        clan_tribe="epic",
        artifacts_dir=str(artifacts),
        response_path=str(response),
        error_message="Mounted representative failure",
        output_variables={"report": "fold exercise complete"},
        model="gpt-5",
    )
    land = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="mounted-land",
        project_file="/tmp/mounted.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 18, 12, 3, 0),
        raw_suffix="20260718120300-land",
        agent_name="sase-mounted.land",
        agent_clan="sase-mounted",
        agent_clan_generation=generation,
        clan_tribe="epic",
        model="gpt-5",
    )
    return sort_and_reorder([phase, land], [])


@pytest.mark.asyncio
async def test_mounted_clan_fold_chords_zoom_and_patch_isolation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_mounted_clan_agents(tmp_path))

    async with AcePage(
        query='"mounted"',
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        patch_folds = (
            page.app.commits_collapsed,
            page.app.hooks_collapsed,
            page.app.mentors_collapsed,
            page.app.timestamps_collapsed,
            page.app.deltas_collapsed,
        )
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        selected = page.app._agents[page.app.current_idx]
        assert selected.is_clan_container
        assert selected.clan_tribes == ("epic",)
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        cached = get_cached_clan_section_snapshot(panel, selected)
        assert cached is not None and cached.disk is not None
        assert len(cached.disk.replies) == 1
        assert len(cached.disk.prompts) == 2

        await page.press("z", "z")
        assert page.app.panel_fold_level is FoldLevel.EXPANDED
        await page.press("z", "Z")
        assert page.app.panel_fold_level is FoldLevel.FULLY_EXPANDED
        await page.press("z", "Z")
        assert page.app.panel_fold_level is FoldLevel.COLLAPSED

        await wait_for_visual_idle(page)
        await page.press("ctrl+j")
        await page.pause()
        assert panel.active_section_identity == "members"

        await page.press("z", "a")
        assert page.app._panel_fold_overrides.get_override("members") is (
            FoldLevel.EXPANDED
        )
        await wait_for_visual_idle(page)
        assert panel.active_section_identity == "members"

        # Numbered roster rows are fold anchors, not Ctrl+J titles, so the
        # cursor now moves straight from "members" to "errors". Reach a
        # roster row's own fold override by scrolling it to the viewport
        # top instead, the same way `za` reaches it in the real product.
        member_anchor = next(
            candidate
            for candidate in getattr(panel, "_section_anchors", ())
            if candidate.identity == "member:sase-mounted.phase"
        )
        scroll = page.query_one_widget("#agent-prompt-scroll", VerticalScroll)
        panel_region = panel.virtual_region
        scroll.scroll_to_region(
            Region(
                panel_region.x,
                panel_region.y + member_anchor.row,
                max(1, panel_region.width),
                1,
            ),
            top=True,
            animate=False,
            x_axis=False,
            y_axis=True,
            immediate=True,
        )
        await wait_for_visual_idle(page)
        await page.press("z", "a")
        assert (
            page.app._panel_fold_overrides.get_override("member:sase-mounted.phase")
            is FoldLevel.EXPANDED
        )

        await page.press("ctrl+j")
        await page.pause()
        assert panel.active_section_identity == "errors"
        await page.press("z", "A")
        assert page.app._panel_fold_overrides.get_override("errors") is (
            FoldLevel.FULLY_EXPANDED
        )
        assert (
            page.app.commits_collapsed,
            page.app.hooks_collapsed,
            page.app.mentors_collapsed,
            page.app.timestamps_collapsed,
            page.app.deltas_collapsed,
        ) == patch_folds

        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        await page.press("z")
        await page.expect_no_modal()

        await page.press("tab")
        await page.expect_state("tab", "patches")
        await page.press("z", "c")
        assert page.app.commits_collapsed is cycle_forward(patch_folds[0])
