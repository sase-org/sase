"""ACE PNG snapshots for the tribe CLAN SUMMARIES intent map."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_clan_fixtures import (
    epic_clan_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    pin_agents_visual_now,
    prompt_header_and_body_text,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_STARTED = datetime(2026, 7, 18, 14, 0, 0)

_EPIC_SUMMARY = """◆ EPIC sase-6n
Title: Ship the runtime phase
Goal: Finish the runtime work first.
Counts: 1/2
"""


def _literal_clan_agents() -> list[Agent]:
    generation = "20260718130000"
    declarer = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-literal-declarer",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 13, 0, 0),
        run_start_time=datetime(2026, 7, 18, 13, 0, 0),
        stop_time=datetime(2026, 7, 18, 13, 5, 0),
        raw_suffix="20260718130000-declarer",
        agent_name="visual-literal.declarer",
        agent_clan="visual-literal-clan",
        agent_clan_generation=generation,
        clan_summary="Audit the release checklist before landing.",
        tribe="epic",
        model="gpt-5",
    )
    joiner = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-literal-joiner",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 18, 13, 1, 0),
        run_start_time=datetime(2026, 7, 18, 13, 1, 0),
        raw_suffix="20260718130100-joiner",
        agent_name="visual-literal.joiner",
        agent_clan="visual-literal-clan",
        agent_clan_generation=generation,
        tribe="epic",
        model="gpt-5",
    )
    return sort_and_reorder([declarer, joiner], [])


def _tribe_clan_summary_agents() -> list[Agent]:
    agents = [*epic_clan_agents(clan_summary=_EPIC_SUMMARY)]
    agents.extend(_literal_clan_agents())
    _apply_status_overrides(agents)
    return sort_and_reorder(agents, [])


async def _jump_to_clan_summaries(page: AcePage) -> AgentPromptPanel:
    panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
    for _ in range(10):
        if panel.active_section_identity == "tribe:clan-summaries":
            break
        await page.press("ctrl+j")
    assert panel.active_section_identity == "tribe:clan-summaries"
    await wait_for_visual_idle(page)
    return panel


async def test_tribe_panel_clan_summaries_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 15, 0, 0))
    patch_startup_loaders(monkeypatch, agents=_tribe_clan_summary_agents())

    async with AcePage(query='"visual-"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 2)
        await wait_for_visual_idle(page)

        await page.press("J")
        assert page.app._panel_group.focused_key == "epic"
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        await page.wait_for(
            lambda _screen: "CLAN SUMMARIES" in prompt_header_and_body_text(panel),
            timeout=30.0,
        )

        await _jump_to_clan_summaries(page)
        await wait_for_svg_contains(page, "CLAN SUMMARIES")
        ace_png_visual.assert_page_png(
            page,
            "agents_tribe_panel_clan_summaries_glance_120x40",
            title="ACE tribe panel clan summaries glance",
        )

        await page.press("z", "3")
        assert page.app.panel_fold_level.value == "fully_expanded"
        await _jump_to_clan_summaries(page)
        await wait_for_svg_contains(page, "CLAN SUMMARIES")
        ace_png_visual.assert_page_png(
            page,
            "agents_tribe_panel_clan_summaries_inspect_120x40",
            title="ACE tribe panel clan summaries inspect",
        )
