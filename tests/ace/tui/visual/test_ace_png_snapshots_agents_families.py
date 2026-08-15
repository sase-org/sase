"""ACE TUI PNG visual snapshots for Agents-tab family list states."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter
from tests.ace.tui.visual._ace_agents_png_snapshot_fixtures import (
    family_and_lone_planner_agents,
    parallel_family_agents,
    parent_navigation_family_agents,
    renamed_generic_family_agents,
    waiting_family_child_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    assert_page_svg_styled_text_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
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

    async with AcePage(query='"visual"', patches=patches()) as page:
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


async def test_python_step_parent_family_footer_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 22, 6, 30, 0))
    patch_startup_loaders(monkeypatch, agents=parent_navigation_family_agents())

    async with AcePage(query='"visual-house-navigation"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("l", "l")
        await page.expect_state("agent_count", 5)
        for _ in range(5):
            if page.app._agents[page.app.current_idx].cl_name == "setup":
                break
            await page.press("j")
        else:
            raise AssertionError("hidden Python setup row was not selectable")
        await wait_for_visual_idle(page)

        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        assert footer._last_layout_inputs is not None
        bindings, _mode_label = footer._last_layout_inputs
        assert ("h", "parent family") in bindings
        assert_page_svg_contains(page, "setup")
        assert_page_svg_contains(page, "parent family")
        ace_png_visual.assert_page_png(
            page,
            "agents_python_step_parent_family_120x40",
            title="ACE Python workflow step parent navigation",
        )

        await page.press("H")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        selected = page.app._agents[page.app.current_idx]
        family_key = selected.raw_suffix
        assert selected.cl_name == "visual-house-navigation"
        assert not selected.is_child_row
        assert family_key is not None
        assert page.app._fold_manager.get(family_key) is FoldLevel.EXPANDED
        assert not any(agent.cl_name == "setup" for agent in page.app._agents)
        assert any(agent.cl_name == "main" for agent in page.app._agents)
        assert any(agent.cl_name == "prepare" for agent in page.app._agents)
        assert any(
            agent.cl_name == "visual-house-navigation-code"
            for agent in page.app._agents
        )
        assert footer._last_layout_inputs is not None
        assert ("H", "collapse family") in footer._last_layout_inputs[0]
        ace_png_visual.assert_page_png(
            page,
            "agents_python_step_hidden_collapsed_120x40",
            title="ACE family hidden-step one-level collapse",
        )

        await page.press("H")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        assert page.app._fold_manager.get(family_key) is FoldLevel.COLLAPSED
        assert page.app._agents[page.app.current_idx].cl_name == (
            "visual-house-navigation"
        )


async def test_renamed_generic_family_root_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 11, 10, 0))
    patch_startup_loaders(monkeypatch, agents=renamed_generic_family_agents())

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("l")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        assert page.app._agents[0].agent_name == "cx--0"
        assert page.app._agents[0].presented_agent_name == "cx"
        assert_page_svg_contains(page, "cx--0")
        assert_page_svg_contains(page, "cx--code")
        ace_png_visual.assert_page_png(
            page,
            "agents_renamed_generic_family_root_120x40",
            title="ACE renamed generic family root",
        )


async def test_parallel_family_root_counts_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 16, 10, 10, 0))
    patch_startup_loaders(monkeypatch, agents=parallel_family_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
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

    async with AcePage(query='"visual"', patches=patches()) as page:
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
