"""Mounted integration tests for Agents-tab fold mode."""

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel, cycle_forward
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation import (
    get_cached_clan_section_snapshot,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
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
async def test_mounted_clan_fold_chords_zoom_and_changespec_isolation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_mounted_clan_agents(tmp_path))

    async with AcePage(
        query='"mounted"',
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        changespec_folds = (
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

        await page.press("ctrl+j")
        await page.pause()
        assert panel.active_section_identity == "member:sase-mounted.phase"

        await page.press("ctrl+j")
        await page.pause()
        assert panel.active_section_identity == "member:sase-mounted.land"

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
        ) == changespec_folds

        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        await page.press("z")
        await page.expect_no_modal()

        await page.press("tab")
        await page.expect_state("tab", "changespecs")
        await page.press("z", "c")
        assert page.app.commits_collapsed is cycle_forward(changespec_folds[0])
