"""ACE PNG snapshots for fold-aware family detail panels and member jumps."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from textual.containers import VerticalScroll
from textual.geometry import Region

from sase.ace.testing import AcePage
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_family_panel_fixtures import (
    _FAMILY_NAME,
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


async def test_family_panel_fold_levels_and_member_override_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(tmp_path, member_count=3, with_content=True),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        container_identity = container.identity
        assert container.is_family_container_row is True
        assert len(page.app._member_jump_maps[container_identity].targets) == 3
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_level_1_120x40",
            title="ACE family panel fold level 1",
        )

        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        for _ in range(20):
            await page.press("ctrl+j")
            if panel.active_section_identity == "agent-xprompt":
                break
        assert panel.active_section_identity == "agent-xprompt"
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_family_conversation_level_1_120x40",
            title="ACE family conversation at fold level 1",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level is FoldLevel.FULLY_EXPANDED
        await wait_for_visual_idle(page)
        assert panel.active_section_identity == "agent-xprompt"
        ace_png_visual.assert_page_png(
            page,
            "agents_family_conversation_level_2_120x40",
            title="ACE family conversation at fold level 2",
        )
        for _ in range(20):
            if panel.active_section_identity is None:
                break
            await page.press("ctrl+j")
        assert panel.active_section_identity is None
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_level_2_120x40",
            title="ACE family panel fold level 2",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level is FoldLevel.EXPANDED
        await wait_for_visual_idle(page)
        assert panel.active_section_identity is None
        await page.press("ctrl+j")
        assert panel.active_section_identity == "members"

        # Numbered roster rows are fold anchors, not Ctrl+J titles, so the
        # next press would jump straight past both member rows. Reach the
        # member row's own fold override by scrolling it to the viewport
        # top instead, the same way `za` reaches it in the real product.
        member_anchor = next(
            candidate
            for candidate in getattr(panel, "_section_anchors", ())
            if candidate.identity == f"member:{_FAMILY_NAME}--code"
        )
        scroll = page.query_one_widget("#agent-prompt-scroll", VerticalScroll)
        panel_region = panel.virtual_region
        scroll.scroll_to_region(
            Region(
                panel_region.x,
                panel_region.y + member_anchor.row,
                max(1, panel_region.width),
                1,
            ),
            top=True,
            animate=False,
            x_axis=False,
            y_axis=True,
            immediate=True,
        )
        await wait_for_visual_idle(page)
        await page.press("z", "a")
        assert (
            page.app._panel_fold_overrides.get_override(f"member:{_FAMILY_NAME}--code")
            is FoldLevel.FULLY_EXPANDED
        )
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_member_override_120x40",
            title="ACE family panel member override",
        )

        await page.press("1")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name
                == f"{_FAMILY_NAME}--code"
            )
        )
        await page.press("apostrophe", "apostrophe")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].identity == container_identity
            )
        )


async def test_family_member_panel_shows_sibling_roster_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(tmp_path, member_count=3, with_content=False),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        assert container.is_family_container_row is True

        await page.press("1")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name
                == f"{_FAMILY_NAME}--code"
            )
        )
        member = page.app._agents[page.app.current_idx]
        assert member.is_family_container_row is False
        await wait_for_visual_idle(page)

        member_jump_map = page.app._member_jump_maps[member.identity]
        member_targets = {target.member_identity for target in member_jump_map.targets}
        assert member.identity not in member_targets

        assert_page_svg_contains(page, "FAMILY SHELLS")
        assert_page_svg_contains(page, "AGENT SHELL")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_member_roster_120x40",
            title="ACE family member panel roster",
        )


async def test_family_two_digit_roster_and_pending_footer_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 30, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(tmp_path, member_count=11, with_content=False),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        container_identity = container.identity
        jump_map = page.app._member_jump_maps[container_identity]
        assert jump_map.targets[0].number == "00"
        assert jump_map.targets[-1].number == "10"
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_two_digit_roster_120x40",
            title="ACE family panel two-digit roster",
        )

        await page.press("1")
        assert page.app._member_jump_pending_digit == "1"
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "shell 1▁")
        assert_page_svg_contains(page, "second digit")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_pending_digit_120x40",
            title="ACE family panel pending shell digit",
        )

        await page.press("0")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name
                == f"{_FAMILY_NAME}--phase-10"
            )
        )
        await page.press("apostrophe", "apostrophe")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].identity == container_identity
            )
        )
