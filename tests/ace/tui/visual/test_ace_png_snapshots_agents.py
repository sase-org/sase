"""ACE TUI PNG visual snapshots for general Agents-tab list states.

Family and clan list snapshots live in the sibling ``*_families`` and
``*_clans`` modules. Agents-tab modal and detail snapshots live in the other
``test_ace_png_snapshots_agents_*`` modules.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui.visual._ace_agents_png_snapshot_fixtures import (
    output_variable_family_agents,
    plan_handoff_status_agents,
    reserved_tribe_wait_agents,
    runner_slot_queue_window_agents,
    runner_slot_wait_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    agents_with_stopped_status,
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agent_list_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_list_120x40",
            title="ACE agents list",
        )


async def test_agent_reverted_indicator_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = agents()
    rows[0].reverted = True
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "↺")
        ace_png_visual.assert_page_png(
            page,
            "agents_reverted_indicator_120x40",
            title="ACE agents reverted indicator",
        )


async def test_agent_stopped_status_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents_with_stopped_status())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Ø STOPPED")
        ace_png_visual.assert_page_png(
            page,
            "agents_stopped_status_120x40",
            title="ACE agents stopped status",
        )


async def test_agent_plan_handoff_status_colors_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=plan_handoff_status_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        for status in (
            "PLAN APPROVED",
            "TALE APPROVED",
            "WORKING PLAN",
            "WORKING TALE",
        ):
            assert_page_svg_contains(page, status)
        ace_png_visual.assert_page_png(
            page,
            "agents_plan_handoff_status_colors_120x40",
            title="ACE agents plan handoff status colors",
        )


async def test_runner_slot_wait_rows_and_queue_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 12, 12, 3, 0))
    monkeypatch.setattr("sase.config.core.get_max_running_agents", lambda: 10)
    patch_startup_loaders(monkeypatch, agents=runner_slot_wait_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        await page.press("j")
        await wait_for_visual_idle(page)
        selected = page.app._agents[page.app.current_idx]
        assert selected.status == "QUEUED"
        assert selected.runner_slot_queue_position == 1
        assert selected.runner_slot_queue_size == 2
        assert_page_svg_contains(page, "drain-barrier")
        assert_page_svg_contains(page, "global-cap")
        assert_page_svg_contains(page, "dependency-wait")
        assert_page_svg_contains(page, "Queue:")
        assert_page_svg_contains(page, "of 2")
        assert_page_svg_contains(page, "at the front")
        prompt = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        prompt_text = renderable_to_text(prompt.content) or ""
        assert "3m in queue" in prompt_text
        assert "QUEUE · 2 waiting · 0/10 runners" in prompt_text
        info = page.app.query_one("#agent-info-panel", AgentInfoPanel)
        assert info._build_display_text().plain.startswith(
            "3  [0/10 running · 2 queued · 1 waiting]"
        )
        ace_png_visual.assert_page_png(
            page,
            "agents_runner_slot_waits_120x40",
            title="ACE agents runner slot waits",
        )

        await page.press("o", "o")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Queued")
        assert_page_svg_contains(page, "Waiting")
        ace_png_visual.assert_page_png(
            page,
            "agents_runner_slot_waits_by_status_120x40",
            title="ACE agents runner slot waits by status",
        )


async def test_reserved_tribe_wait_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=reserved_tribe_wait_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "WAITING")
        assert_page_svg_contains(page, "!")
        prompt = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        prompt_text = renderable_to_text(prompt.content) or ""
        assert "Wait: [tribes] @default ! (reserved - never resolves)" in prompt_text
        assert "(next launch)" not in prompt_text
        ace_png_visual.assert_page_png(
            page,
            "agents_reserved_tribe_wait_120x40",
            title="ACE agents reserved tribe wait",
        )


async def test_runner_slot_queue_window_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = runner_slot_queue_window_agents()
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 25, 12, 12, 0))
    monkeypatch.setattr("sase.config.core.get_max_running_agents", lambda: 10)
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 9)
        await wait_for_visual_idle(page)

        for _ in range(len(rows) + 1):
            selected = (
                page.app._agents[page.app.current_idx]
                if 0 <= page.app.current_idx < len(page.app._agents)
                else None
            )
            if selected is not None and selected.agent_name == "queue-middle":
                break
            await page.press("j")
            await wait_for_visual_idle(page)
        selected = page.app._agents[page.app.current_idx]
        assert selected.agent_name == "queue-middle"
        assert selected.runner_slot_queue_position == 6
        prompt = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        prompt_text = renderable_to_text(prompt.content) or ""
        assert "4 ahead" in prompt_text
        assert "QUEUE · 9 waiting · 0/10 runners" in prompt_text
        assert "≤0" in prompt_text
        assert "p1" in prompt_text
        assert "… +2 more" in prompt_text
        assert "… +1 more" in prompt_text
        ace_png_visual.assert_page_png(
            page,
            "agents_runner_slot_queue_window_120x40",
            title="ACE agents runner slot queue window",
        )


async def test_agent_output_variables_multi_agent_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 8, 9, 9, 0))
    patch_startup_loaders(monkeypatch, agents=output_variable_family_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "OUTPUT VARIABLES")
        assert_page_svg_contains(page, "· 4")
        assert_page_svg_contains(page, "build_report")
        assert_page_svg_contains(page, "summary")
        ace_png_visual.assert_page_png(
            page,
            "agents_output_variables_multi_agent_120x40",
            title="ACE agents output variables multi agent",
        )


async def test_agents_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
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
        )
