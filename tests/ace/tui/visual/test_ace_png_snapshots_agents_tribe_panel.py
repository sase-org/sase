"""ACE PNG snapshots for the four fold-aware tribe detail levels."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.visual.test_ace_png_snapshots_agents import (
    _pin_agents_visual_now,
)

pytestmark = pytest.mark.visual


def _tribe_agents() -> list[Agent]:
    started = datetime(2026, 7, 18, 14, 0, 0)
    family_root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-tribe-build--plan",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=started,
        run_start_time=started,
        raw_suffix="visual-tribe-plan",
        agent_name="visual-tribe-build--plan",
        agent_family="visual-tribe-build",
        agent_family_role="root",
        role_suffix="--plan",
        plan_chain_root=True,
        model="gpt-5",
        tribe="epic",
    )
    family_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-tribe-build--code",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 18, 14, 2, 0),
        run_start_time=datetime(2026, 7, 18, 14, 2, 0),
        raw_suffix="visual-tribe-code",
        parent_timestamp=family_root.raw_suffix,
        agent_name="visual-tribe-build--code",
        agent_family="visual-tribe-build",
        agent_family_role="code",
        role_suffix="--code",
        model="gpt-5",
        workspace_num=15,
        activity="waiting for verification",
        tribe="epic",
    )
    family_root.followup_agents = [family_child]
    failed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-tribe-review",
        project_file="/workspace/sase/visual_project.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 18, 14, 5, 0),
        run_start_time=datetime(2026, 7, 18, 14, 5, 0),
        stop_time=datetime(2026, 7, 18, 14, 8, 0),
        raw_suffix="visual-tribe-review",
        agent_name="visual-tribe-review",
        model="gpt-5",
        tribe="epic",
        error_message="Verification failed\nDetailed forensics line",
        error_traceback="Traceback (most recent call last):\nValueError: visual failure",
        output_variables={"report": "triage summary\ncomplete report body"},
    )
    home = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-home",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=started,
        run_start_time=started,
        stop_time=datetime(2026, 7, 18, 14, 10, 0),
        raw_suffix="visual-home",
        agent_name="visual-home",
    )
    return [home, family_root, family_child, failed]


async def test_tribe_panel_four_level_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 15, 0, 0))
    patch_startup_loaders(monkeypatch, agents=_tribe_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        await page.press("J")
        assert page.app._panel_group.focused_key == "epic"
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )

        await page.press("H")
        await page.wait_for(
            lambda _screen: (
                None in page.app._collapsed_panel_keys
                and page.app._panel_isolation_revert is not None
            )
        )
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "↺")
        ace_png_visual.assert_page_png(
            page,
            "agents_tribe_panel_isolation_armed_120x40",
            title="ACE tribe panel isolation restore markers",
        )

        await page.press("H")
        await page.wait_for(
            lambda _screen: (
                None not in page.app._collapsed_panel_keys
                and page.app._panel_isolation_revert is None
            )
        )
        await page.press("h")
        await page.wait_for(lambda _screen: "epic" in page.app._collapsed_panel_keys)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "TRIBE")
        assert_page_svg_contains(page, "@epic")
        assert_page_svg_contains(page, "NEEDS ATTENTION")
        assert page.app._member_jump_maps[("panel", "epic")].targets
        ace_png_visual.assert_page_png(
            page,
            "agents_tribe_panel_level_1_120x40",
            title="ACE tribe panel glance",
        )

        await page.press("z", "1")
        assert page.app.panel_fold_level.value == "collapsed"
        assert page.app._member_jump_pending_digit is None

        for position, fold_value, snapshot_name, title in (
            (
                "2",
                "expanded",
                "agents_tribe_panel_level_2_120x40",
                "ACE tribe panel triage",
            ),
            (
                "3",
                "fully_expanded",
                "agents_tribe_panel_level_3_120x40",
                "ACE tribe panel inspect",
            ),
            (
                "4",
                "exhaustive",
                "agents_tribe_panel_level_4_120x40",
                "ACE tribe panel forensics",
            ),
        ):
            selected_idx = page.app.current_idx
            await page.press("z", position)
            assert page.app.panel_fold_level.value == fold_value
            assert page.app._member_jump_pending_digit is None
            assert page.app.current_idx == selected_idx
            assert page.app._resolve_focused_panel() is not None
            await wait_for_visual_idle(page)
            ace_png_visual.assert_page_png(page, snapshot_name, title=title)

        assert page.app._member_jump_maps[("panel", "epic")].targets
        await page.press("1")
        await page.wait_for(
            lambda _screen: (
                page.app._agents[page.app.current_idx].agent_name
                == "visual-tribe-review"
            )
        )
        assert page.app._resolve_focused_panel() is None

        # Member jumps publish a panel anchor. Fast back-jump must restore
        # whole-panel focus without moving the remembered row, even though the
        # member jump expanded the formerly collapsed panel.
        await page.press("ctrl+o")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        focus = page.app._resolve_focused_panel()
        assert focus is not None
        assert focus.panel_key == "epic"
        assert focus.collapsed is False
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "❖ @epic")
        ace_png_visual.assert_page_png(
            page,
            "agents_tribe_panel_selected_expanded_120x40",
            title="ACE selected expanded tribe panel",
        )

        # Complete the four-level wrap, then exercise lower-case panel cycling
        # across expanded and collapsed destinations without descending.
        await page.press("z", "z")
        assert page.app.panel_fold_level.value == "collapsed"
        await page.press("h")
        await page.wait_for(lambda _screen: "epic" in page.app._collapsed_panel_keys)
        await page.press("j")
        focus = page.app._resolve_focused_panel()
        assert focus is not None
        assert focus.panel_key is None
        assert focus.collapsed is False
        await page.press("k")
        focus = page.app._resolve_focused_panel()
        assert focus is not None
        assert focus.panel_key == "epic"
        assert focus.collapsed is True
