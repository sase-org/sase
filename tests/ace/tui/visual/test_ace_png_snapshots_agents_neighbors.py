"""ACE TUI PNG visual snapshots for Agents-tab neighbor interactions."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentList, KeybindingFooter
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    hood_neighbor_agents,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _neighbor_panel_reveal_agents() -> list[Agent]:
    """Single neighbor target inside a collapsed, reorderable tribe panel."""
    project_file = "/workspace/sase/visual_project.sase"
    started = datetime(2026, 7, 18, 16, 30, 0)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-neighbor-origin",
            project_file=project_file,
            status="RUNNING",
            start_time=started,
            raw_suffix="20260718-163000-neighbor-origin",
            agent_name="visual.jump.plan",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-neighbor-target",
            project_file=project_file,
            status="DONE",
            start_time=started,
            stop_time=datetime(2026, 7, 18, 16, 36, 0),
            raw_suffix="20260718-163100-neighbor-target",
            agent_name="visual.jump.code",
            tribe="alpha",
            agent_clan="visual-workers",
            agent_clan_generation="20260718-163100",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-neighbor-unrelated",
            project_file=project_file,
            status="WAITING",
            start_time=started,
            raw_suffix="20260718-163200-neighbor-unrelated",
            agent_name="unrelated.agent",
            tribe="zeta",
        ),
    ]


def _folded_clan_neighbor_modal_agents() -> list[Agent]:
    """Two hidden hood neighbors, one also inside a collapsed tribe panel."""
    agents = _neighbor_panel_reveal_agents()
    peer = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-neighbor-peer",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 18, 16, 32, 0),
        raw_suffix="20260718-163200-neighbor-peer",
        agent_name="visual.jump.review",
        tribe="beta",
        agent_clan="visual-reviewers",
        agent_clan_generation="20260718-163200",
    )
    return [agents[0], agents[1], peer, agents[2]]


async def test_agents_neighbor_badge_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=hood_neighbor_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_svg_contains(page, "neighbors: ")
        await wait_for_visual_idle(page)
        neighbor_index = page.app._agent_neighbor_index()
        assert neighbor_index.neighbor_count(page.app.current_idx) == 3
        assert_page_svg_contains(page, "neighbors: ")

        ace_png_visual.assert_page_png(
            page,
            "agents_neighbor_badge_120x40",
            title="ACE agents neighbor badge",
        )


async def test_agents_neighbor_jump_expands_target_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _neighbor_panel_reveal_agents()
    target = agents[1]
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)

        await page.press("J")
        assert page.app._panel_group.focused_key == "alpha"
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        await page.press("h")
        await page.wait_for(lambda _screen: "alpha" in page.app._collapsed_panel_keys)
        assert page.app._panel_group.panel_keys == [None, "zeta", "alpha"]
        await page.press("J")
        assert page.app._panel_group.focused_key is None
        assert page.app._agents[page.app.current_idx].identity == agents[0].identity

        page.app.action_start_sibling_mode()
        await page.wait_for(
            lambda _screen: "alpha" not in page.app._collapsed_panel_keys
        )
        await wait_for_visual_idle(page)

        assert page.app._panel_group.panel_keys == [None, "alpha", "zeta"]
        assert page.app._panel_group.focused_key == "alpha"
        assert page.app._agents[page.app.current_idx].identity == target.identity
        target_widget = page.app.query_one("#agent-list-panel-1", AgentList)
        assert target_widget.highlighted is not None

        ace_png_visual.assert_page_png(
            page,
            "agents_neighbor_jump_expanded_panel_120x40",
            title="ACE folded-clan neighbor jump expanded panel",
        )


async def test_agent_neighbor_modal_folded_clan_and_tribe_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _folded_clan_neighbor_modal_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(70, 32)
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")

        await page.press("J")
        assert page.app._panel_group.focused_key == "alpha"
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        await page.press("h")
        await page.wait_for(lambda _screen: "alpha" in page.app._collapsed_panel_keys)
        await page.press("J")
        assert page.app._panel_group.focused_key is None

        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentNeighborModal")
        await wait_for_svg_contains(page, "visual.jump.code")
        await wait_for_visual_idle(page)

        modal = page.app.screen_stack[-1]
        choices = vars(modal)["_choices"]
        assert [choice.agent_name for choice in choices] == [
            "visual.jump.review",
            "visual.jump.code",
        ]
        assert [choice.panel_label for choice in choices] == ["@beta", "@alpha"]
        assert [choice.global_idx for choice in choices] == [None, None]

        ace_png_visual.assert_page_png(
            page,
            "agent_neighbor_folded_clan_modal_70x32",
            title="ACE folded-clan neighbor chooser",
        )


async def test_agent_neighbor_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=hood_neighbor_agents())

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentNeighborModal")
        await wait_for_svg_contains(page, "Neighbors of visual.code.plan")
        await wait_for_visual_idle(page)
        modal = page.app.screen_stack[-1]
        assert modal.__class__.__name__ == "AgentNeighborModal"
        choices = vars(modal)["_choices"]
        assert [choice.global_idx for choice in choices] == [1, 2, 3]
        assert [choice.hood for choice in choices] == [
            "visual.code",
            "visual.code",
            "visual",
        ]
        assert_page_svg_contains(page, "Neighbors of visual.code.plan")
        assert_page_svg_contains(page, "visual.code.implementation")

        ace_png_visual.assert_page_png(
            page,
            "agent_neighbor_modal_60x30",
            title="ACE agent neighbor modal narrow",
        )


async def test_agent_neighbor_modal_dismissed_descendant_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 23, 13, 0, 0),
        raw_suffix="20260523-130000-parent",
        agent_name="visual.root",
        tribe="api",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-child",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 13, 8, 0),
        stop_time=datetime(2026, 5, 23, 13, 12, 30),
        raw_suffix="20260523-130800-child",
        agent_name="visual.root.visible",
        tribe="api",
    )
    dismissed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-dismissed",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 23, 13, 16, 0),
        stop_time=datetime(2026, 5, 23, 13, 17, 5),
        raw_suffix="20260523-131600-dismissed",
        agent_name="visual.root.dismissed",
        tribe="api",
    )
    patch_startup_loaders(monkeypatch, agents=[parent, child])

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 2)
        page.app._dismissed_agent_objects = [dismissed]
        page.app._dismissed_agents = {dismissed.identity}
        page.app._dismiss_revive_epoch += 1
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentNeighborModal")
        page.app._refresh_agent_footer_bindings_only()
        # The direct private-state mutation above bypasses the normal action
        # path that refreshes the footer. Repaint it explicitly, then wait on
        # footer state specifically: the modal's "2 descendants" text can
        # otherwise satisfy a broad SVG poll while the footer is still stale.
        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        await page.wait_for(
            lambda _screen: (
                footer._last_layout_inputs is not None
                and any(
                    label == "neighbors (2)"
                    for _key, label in footer._last_layout_inputs[0]
                )
            )
        )
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Descendants")
        assert_page_svg_contains(page, "visual.root.dismissed")
        assert_page_svg_contains(page, "dismissed")

        ace_png_visual.assert_page_png(
            page,
            "agent_neighbor_modal_descendants_dismissed_60x30",
            title="ACE agent neighbor modal dismissed descendant",
        )
