"""ACE PNG snapshots for family panel monitor shell metadata and conversation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent_family_members import concrete_family_shell_rows
from sase.ace.tui.widgets import AgentList
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_family_panel_fixtures import (
    _family_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
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


async def test_family_panel_shells_monitor_metadata_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(
            tmp_path,
            member_count=2,
            with_content=False,
            with_monitor=True,
            monitor_command=(
                "just check-full --include visual --include slow "
                "--include every-family-shell-metadata-case"
            ),
            monitor_reason=(
                "Full-suite verification before landing the family shell "
                "metadata renderer"
            ),
        ),
    )

    async with AcePage(
        query='"visual-family-root"',
        size=(120, 40),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        assert container.is_family_container_row is True
        shells = concrete_family_shell_rows(container)
        assert [shell.is_monitor for shell in shells] == [False, False, True]
        monitor = shells[2]
        assert monitor.parent_timestamp != container.raw_suffix
        jump_map = page.app._member_jump_maps[container.identity]
        assert [target.number for target in jump_map.targets] == ["0", "1", "2"]
        assert jump_map.targets[2].member_identity == monitor.identity
        assert_page_svg_contains(page, "Shells:")
        assert_page_svg_contains(page, "⚙")
        assert_page_svg_contains(page, "why")
        assert_page_svg_contains(page, "Full-suite")
        assert_page_svg_contains(page, "verification")
        assert_page_svg_contains(page, "FAMILY SHELLS")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_shells_monitor_120x40",
            title="ACE family panel shell metadata with monitor",
        )

        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        for _ in range(20):
            if panel.active_section_identity == "members":
                break
            await page.press("ctrl+j")
        assert panel.active_section_identity == "members"
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "FAMILY SHELLS")
        assert_page_svg_contains(page, "--plan")
        assert_page_svg_contains(page, "--mon")
        assert_page_svg_contains(page, "⚙ MONITOR")
        assert_page_svg_contains(page, "just check")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_shells_monitor_roster_120x40",
            title="ACE family panel FAMILY SHELLS roster with monitor",
        )

        await page.press("2")
        await page.wait_for(
            lambda _state: page.app._agents[page.app.current_idx].is_monitor
        )
        assert page.app._agents[page.app.current_idx].identity == monitor.identity


async def test_family_conversation_monitor_phase_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(
            tmp_path,
            member_count=2,
            with_content=False,
            with_monitor=True,
        ),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        assert container.is_family_container_row is True
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        for _ in range(20):
            await page.press("ctrl+j")
            if panel.active_section_identity == "agent-reply":
                break
        assert panel.active_section_identity == "agent-reply"
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "MONITOR")
        assert_page_svg_contains(page, "just check-full")
        panel = page.app.query_one("#agent-list-panel", AgentList)
        assert "⚙1" in Text.from_markup(panel.border_title).plain
        ace_png_visual.assert_page_png(
            page,
            "agents_family_conversation_monitor_120x40",
            title="ACE family conversation with monitor phase",
        )
