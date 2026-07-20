"""ACE PNG snapshots for fold-aware epic and swarm clan detail panels."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent_associated_plan import _AgentPlanEnrichment
from tests.ace.tui.visual._ace_agents_png_snapshot_clan_fixtures import (
    clan_tree_agents,
    decorate_clan_panel_sections,
    epic_clan_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_RESEARCH_CLAN_SUMMARY = (
    "[bold #FFD75F]RESEARCH PROMPT:[/bold #FFD75F]\n"
    "[italic #D7D7FF]How do clan summaries stay fast, safe, and beautiful\n"
    "across every fold level?[/italic #D7D7FF]"
)

_EPIC_CLAN_SUMMARY = (
    "[bold #D75FFF]EPIC sase-6n · Rich clan summaries[/bold #D75FFF]\n"
    "[dim #D7D7FF]Share launch context without live lookups or render-time "
    "subprocesses.[/dim #D7D7FF]\n"
    "[bold #87D7FF]1.[/bold #87D7FF] Persist summaries at launch\n"
    "[bold #87D7FF]2.[/bold #87D7FF] Render Rich markup safely\n"
    "[bold #87D7FF]3.[/bold #87D7FF] Ship epic and research presets"
)


@pytest.fixture(autouse=True)
def _isolate_clan_plan_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep clan fold goldens independent of the ambient bead/plan store."""
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_plan_enrichment",
        lambda *_args, **_kwargs: _AgentPlanEnrichment(
            "ordinary",
            None,
            None,
            None,
        ),
    )


async def test_epic_clan_panel_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 17, 12, 15, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=decorate_clan_panel_sections(
            epic_clan_agents(clan_summary=_EPIC_CLAN_SUMMARY)
        ),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "CLAN")
        assert_page_svg_contains(page, "sase-6n")
        assert_page_svg_contains(page, "Rich clan summaries")
        assert_page_svg_contains(page, "Render Rich markup safely")
        assert_page_svg_contains(page, "3 agents")
        assert_page_svg_contains(page, ".land")
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_panel_epic_120x40",
            title="ACE epic clan panel fold level 1",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level.value == "expanded"
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_panel_epic_level_2_120x40",
            title="ACE epic clan panel fold level 2",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level.value == "fully_expanded"
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_panel_epic_level_3_120x40",
            title="ACE epic clan panel fold level 3",
        )

        container_identity = page.app._agents[page.app.current_idx].identity
        await page.press("1")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name == "sase-6n.phase-tui"
            )
        )
        await page.press("apostrophe", "apostrophe")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].identity == container_identity
            )
        )


async def test_swarm_clan_panel_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 17, 10, 15, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=decorate_clan_panel_sections(
            clan_tree_agents(clan_summary=_RESEARCH_CLAN_SUMMARY)
        ),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "CLAN")
        assert_page_svg_contains(page, "RESEARCH PROMPT:")
        assert_page_svg_contains(page, "across every fold level?")
        assert_page_svg_contains(page, "3 agents")
        assert_page_svg_contains(page, "1 family")
        assert_page_svg_contains(page, "--code")
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_panel_swarm_120x40",
            title="ACE swarm clan panel fold level 1",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level.value == "expanded"
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_panel_swarm_level_2_120x40",
            title="ACE swarm clan panel fold level 2",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level.value == "fully_expanded"
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_panel_swarm_level_3_120x40",
            title="ACE swarm clan panel fold level 3",
        )
