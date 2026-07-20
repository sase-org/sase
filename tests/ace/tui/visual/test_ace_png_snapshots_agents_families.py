"""ACE TUI PNG visual snapshots for Agents-tab family list states."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_agents_png_snapshot_fixtures import (
    family_and_lone_planner_agents,
    parallel_family_agents,
    renamed_plan_family_agents,
    waiting_family_child_agents,
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


async def test_waiting_family_child_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=waiting_family_child_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("l")
        await page.expect_state("agent_count", 2)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "visual-parent")
        assert_page_svg_contains(page, "RUNNING")
        assert_page_svg_contains(page, "visual-parent--reviewer")
        assert_page_svg_contains(page, "WAITING")
        ace_png_visual.assert_page_png(
            page,
            "agents_waiting_family_child_120x40",
            title="ACE agents waiting family child",
        )


async def test_renamed_plan_family_root_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 11, 10, 0))
    patch_startup_loaders(monkeypatch, agents=renamed_plan_family_agents())

    async with AcePage(query='"visual-family"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("l")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        assert page.app._agents[0].agent_name == "cx--plan"
        assert page.app._agents[0].presented_agent_name == "cx"
        assert_page_svg_contains(page, "cx--plan")
        assert_page_svg_contains(page, "cx--code")
        ace_png_visual.assert_page_png(
            page,
            "agents_renamed_plan_family_root_120x40",
            title="ACE renamed plan family root",
        )


async def test_parallel_family_root_counts_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 16, 10, 10, 0))
    patch_startup_loaders(monkeypatch, agents=parallel_family_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "visual-parallel-family")
        assert_page_svg_styled_text_contains(page, "[R2 D1]")
        # (unread, stopped, running, waiting, failed, done, total, starting)
        assert page.app._agent_info_metrics() == (0, 0, 2, 0, 0, 1, 3, 0)
        ace_png_visual.assert_page_png(
            page,
            "agents_parallel_family_counts_120x40",
            title="ACE parallel family aggregate counts",
        )


async def test_family_and_lone_planner_color_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 12, 15, 0))
    rows = family_and_lone_planner_agents()
    family = next(row for row in rows if row.cl_name == "visual-real-family")
    lone_planner = next(row for row in rows if row.cl_name == "visual-lone-planner")
    assert family.is_family_container_row is True
    assert lone_planner.is_family_container_row is False
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 2)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "visual-real-family")
        assert_page_svg_contains(page, "visual-lone-planner")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_and_lone_planner_color_120x40",
            title="ACE family and lone planner color contrast",
        )
