"""ACE TUI PNG visual snapshots for Agents-tab clan tree states."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree
from sase.ace.tui.widgets.agent_list import AgentList
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_clan_fixtures import (
    clan_tree_agents,
    queued_clan_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    assert_page_svg_styled_text_contains,
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


async def test_queued_clan_counts_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.config.core.get_max_running_agents", lambda: 10)
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 24, 12, 5, 0))
    patch_startup_loaders(monkeypatch, agents=queued_clan_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert page.app._agents[0].is_clan_container is True
        panel = page.app.query_one("#agent-list-panel", AgentList)
        assert Text.from_markup(panel.border_title).plain == "▲ @epic · 2 [Q1 W1]"
        list_rows = "\n".join(
            option.prompt.plain
            for option in panel._options  # type: ignore[union-attr]
        )
        assert "(QUEUED) ×2 [Q1 W1]" in list_rows
        prompt = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        assert "Status: QUEUED [Q1 W1]" in prompt.content.plain
        info = page.app.query_one("#agent-info-panel", AgentInfoPanel)
        assert info._build_display_text().plain.startswith(
            "2  [0/10 running · 1 queued · 1 waiting]"
        )
        status_group_keys = [
            entry.group.group_key
            for entry in build_agent_tree(
                page.app._agents,
                mode=GroupingMode.BY_STATUS,
            )
            if entry.group is not None
        ]
        assert status_group_keys == [("Queued",)]
        ace_png_visual.assert_page_png(
            page,
            "agents_queued_clan_counts_120x40",
            title="ACE queued clan counts",
        )


async def test_clan_tree_fold_levels_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 17, 10, 15, 0))
    patch_startup_loaders(monkeypatch, agents=clan_tree_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert page.app._agents[0].is_clan_container is True
        assert page.app._agents[0].clan_tribes == ("epic", "review")
        assert_page_svg_contains(page, "research")
        assert_page_svg_styled_text_contains(page, "[R1 W1 D1]")
        assert_page_svg_contains(page, "@epic")
        assert_page_svg_contains(page, "@review")
        # The clan has three direct lanes (family, workflow, standalone), and
        # the status buckets retain the loaded concrete family member.
        assert page.app._agent_info_metrics() == (0, 0, 1, 1, 0, 1, 3, 0)
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_tree_collapsed_120x40",
            title="ACE clan tree collapsed",
        )

        await page.press("l")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "research.family")
        assert_page_svg_contains(page, "research.audit")
        assert all(
            agent.agent_name != "research.family--code" for agent in page.app._agents
        )
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_tree_expanded_120x40",
            title="ACE clan tree expanded",
        )

        await page.press("j", "j", "j")
        assert page.app._agents[page.app.current_idx].agent_name == "research.audit"
        await page.press("l")
        await page.expect_state("agent_count", 5)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "audit-prompt")
        assert all(not agent.is_hidden_step for agent in page.app._agents)
        assert all(
            agent.agent_name != "research.family--code" for agent in page.app._agents
        )
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_tree_member_expanded_120x40",
            title="ACE clan member expanded",
        )

        await page.press("l")
        await page.expect_state("agent_count", 6)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "setup")
        assert all(
            agent.agent_name != "research.family--code" for agent in page.app._agents
        )
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_tree_fully_expanded_120x40",
            title="ACE clan member fully expanded",
        )

        await page.press("o", "o")
        await wait_for_visual_idle(page)
        assert page.app._grouping_mode is GroupingMode.BY_STATUS
        assert page.app._panel_group.panel_keys == [None]
        status_group_keys = [
            entry.group.group_key
            for entry in build_agent_tree(
                page.app._agents,
                mode=GroupingMode.BY_STATUS,
            )
            if entry.group is not None
        ]
        assert status_group_keys == [("Running",)]
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_tree_fully_expanded_by_status_120x40",
            title="ACE clan member fully expanded by status",
        )


async def test_clan_unread_count_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 17, 10, 15, 0))
    patch_startup_loaders(monkeypatch, agents=clan_tree_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)

        unread_member = next(
            agent
            for agent in page.app._agents_with_children
            if not agent.is_clan_container
            and agent.tree_depth == 1
            and agent.status == "DONE"
        )
        page.app._unread_completed_agent_ids.add(unread_member.identity)
        page.app._manual_unread_agent_ids.add(unread_member.identity)
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)

        assert_page_svg_styled_text_contains(page, "[R1 W1 U1]")
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_unread_collapsed_120x40",
            title="ACE unread clan collapsed",
        )

        await page.press("l")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)
        assert_page_svg_styled_text_contains(page, "[R1 W1 U1]")
        ace_png_visual.assert_page_png(
            page,
            "agents_clan_unread_expanded_120x40",
            title="ACE unread clan expanded",
        )
