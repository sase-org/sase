"""ACE TUI PNG visual snapshot coverage for the ChangeSpecs and Agents tabs.

Axe-tab PNG snapshot coverage lives in ``test_ace_png_snapshots_axe``.
Shared fixtures live in ``_ace_png_snapshot_helpers``.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    changespecs,
    patch_startup_loaders,
    sibling_agents,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03


def _assert_page_svg_contains(page: AcePage, text: str) -> None:
    svg = page.export_svg(title="ACE visual assertion")
    svg_plain = svg.replace("&#160;", " ")
    assert text in svg_plain


async def test_changespec_initial_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await page.expect_state("selected.name", "visual_auth")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "changespec_initial_120x40",
            title="ACE changespec initial",
        )


async def test_changespec_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await page.press("j")
        await page.expect_state("selected.name", "visual_billing")
        page.app._refresh_changespec_detail_only()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "changespec_selected_row_120x40",
            title="ACE changespec selected row",
        )


async def test_query_edit_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await page.press("slash")
        await page.expect_modal("QueryEditModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "query_edit_modal_120x40",
            title="ACE query edit modal",
        )


async def test_agent_list_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_list_120x40",
            title="ACE agents list",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        initial_idx = page.app.current_idx
        for _ in range(8):
            await page.press("j")
            if page.app.current_idx != initial_idx:
                break
        else:
            raise AssertionError("j navigation did not move off the initial agent row")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_selected_row_120x40",
            title="ACE agents selected row",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


def _done_agents() -> list[Agent]:
    """Three completed agents in the ``Done`` bucket.

    Used by the unread-highlight snapshot — all three rows are then
    marked unread post-startup so the Agents-tab info-panel header
    renders a non-zero ``N unread`` count that exercises the yellow
    background style.
    """
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            stop_time=datetime(2026, 5, 9, 10, 7, 30),
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            llm_provider="codex",
            model="gpt-5",
            response_path="/workspace/sase/artifacts/visual-plan/response.md",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 8, 0),
            stop_time=datetime(2026, 5, 9, 10, 9, 5),
            raw_suffix="20260509-100800-code",
            agent_name="coder",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-review",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN DONE",
            start_time=datetime(2026, 5, 9, 10, 10, 0),
            stop_time=datetime(2026, 5, 9, 10, 12, 0),
            raw_suffix="20260509-101000-review",
            agent_name="reviewer",
            tag="visual",
        ),
    ]


async def _render_leader_footer(page: AcePage) -> None:
    """Force the keybinding footer into LEADER mode and let it lay out.

    LEADER mode is the worst case for footer width — ~15 chips on changespecs
    tab — so it's the right target for grid-overflow snapshots.
    """
    from sase.ace.tui.widgets import KeybindingFooter

    footer = page.app.query_one(KeybindingFooter)
    footer.update_leader_bindings(current_tab="changespecs")
    await wait_for_visual_idle(page)


async def test_footer_leader_overflow_wide_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LEADER mode at 120x40: chips overflow into a deterministic grid."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _render_leader_footer(page)

        ace_png_visual.assert_page_png(
            page,
            "footer_leader_overflow_120x40",
            title="ACE footer LEADER grid (wide)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_footer_leader_overflow_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LEADER mode at 80x30: narrower width drops more chips into more rows."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(80, 30)
    ) as page:
        await wait_for_startup(page)
        await _render_leader_footer(page)

        ace_png_visual.assert_page_png(
            page,
            "footer_leader_overflow_80x30",
            title="ACE footer LEADER grid (narrow)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_unread_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = _done_agents()
    patch_startup_loaders(monkeypatch, agents=done)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        identities = {agent.identity for agent in done}
        page.app._unread_completed_agent_ids = set(identities)
        page.app._manual_unread_agent_ids = set(identities)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app._update_agents_info_panel()
        from sase.ace.tui.widgets import AgentInfoPanel

        panel = page.app.query_one("#agent-info-panel", AgentInfoPanel)
        assert panel._unread_count == 3, f"expected 3 unread, got {panel._unread_count}"
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_unread_highlight_120x40",
            title="ACE agents unread highlight",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_sibling_badge_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=sibling_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)
        assert page.app._agent_sibling_index().sibling_count(page.app.current_idx) == 2
        _assert_page_svg_contains(page, "siblings: ")

        ace_png_visual.assert_page_png(
            page,
            "agents_sibling_badge_120x40",
            title="ACE agents sibling badge",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agent_sibling_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=sibling_agents())

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentSiblingModal")
        await wait_for_visual_idle(page)
        modal = page.app.screen_stack[-1]
        assert modal.__class__.__name__ == "AgentSiblingModal"
        choices = vars(modal)["_choices"]
        assert [choice.global_idx for choice in choices] == [1, 2]
        _assert_page_svg_contains(page, "Sibling Agents: visual.*")
        _assert_page_svg_contains(page, "visual.code.implementation.with...")

        ace_png_visual.assert_page_png(
            page,
            "agent_sibling_modal_60x30",
            title="ACE agent sibling modal narrow",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
