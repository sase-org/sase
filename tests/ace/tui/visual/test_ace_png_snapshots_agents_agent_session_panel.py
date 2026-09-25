"""ACE PNG snapshots for fold-aware session detail panels and member jumps."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.fold_state import FoldLevel
from tests.ace.tui.visual._ace_agents_png_snapshot_agent_session_panel_fixtures import (
    _AGENT_SESSION_NAME,
    _agent_session_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    main_deck_scroll,
    pin_agents_visual_now,
    pin_decks_paged,
    resolved_main_section,
    scroll_main_section_to_top,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agent_session_panel_fold_levels_and_member_override_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    pin_decks_paged(monkeypatch)
    patch_startup_loaders(
        monkeypatch,
        agents=_agent_session_agents(tmp_path, member_count=3, with_content=True),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        container_identity = container.identity
        assert container.is_agent_session_container_row is True
        assert len(page.app._member_jump_maps[container_identity].targets) == 3
        ace_png_visual.assert_page_png(
            page,
            "agents_session_panel_level_1_120x40",
            title="ACE session panel fold level 1",
        )

        await scroll_main_section_to_top(page, "agent-prompt")
        ace_png_visual.assert_page_png(
            page,
            "agents_session_conversation_level_1_120x40",
            title="ACE session conversation at fold level 1",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level is FoldLevel.FULLY_EXPANDED
        await wait_for_visual_idle(page)
        assert resolved_main_section(page) == "agent-prompt"
        ace_png_visual.assert_page_png(
            page,
            "agents_session_conversation_level_2_120x40",
            title="ACE session conversation at fold level 2",
        )
        # Wrapping back to the top: the Main deck starts at its first section.
        scroll = main_deck_scroll(page)
        scroll.scroll_to(y=0, animate=False, immediate=True)
        await wait_for_visual_idle(page)
        assert int(scroll.scroll_y) == 0
        assert resolved_main_section(page) == "output-variables"
        ace_png_visual.assert_page_png(
            page,
            "agents_session_panel_level_2_120x40",
            title="ACE session panel fold level 2",
        )

        await page.press("z", "z")
        assert page.app.panel_fold_level is FoldLevel.EXPANDED
        await wait_for_visual_idle(page)
        assert resolved_main_section(page) == "output-variables"

        await page.press("1")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name
                == f"{_AGENT_SESSION_NAME}--code"
            )
        )
        await page.press("apostrophe", "apostrophe")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].identity == container_identity
            )
        )


async def test_agent_session_member_panel_shows_sibling_roster_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_agent_session_agents(tmp_path, member_count=3, with_content=False),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        assert container.is_agent_session_container_row is True

        await page.press("1")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name
                == f"{_AGENT_SESSION_NAME}--code"
            )
        )
        member = page.app._agents[page.app.current_idx]
        assert member.is_agent_session_container_row is False
        await wait_for_visual_idle(page)

        member_jump_map = page.app._member_jump_maps[member.identity]
        member_targets = {target.member_identity for target in member_jump_map.targets}
        assert member.identity not in member_targets

        assert_page_svg_contains(page, "SESSION SHELLS")
        assert_page_svg_contains(page, "AGENT SHELL")
        ace_png_visual.assert_page_png(
            page,
            "agents_session_panel_member_roster_120x40",
            title="ACE session member panel roster",
        )


async def test_agent_session_two_digit_roster_and_pending_footer_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 30, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_agent_session_agents(tmp_path, member_count=11, with_content=False),
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
            "agents_session_panel_two_digit_roster_120x40",
            title="ACE session panel two-digit roster",
        )

        await page.press("1")
        assert page.app._member_jump_pending_digit == "1"
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "shell 1▁")
        assert_page_svg_contains(page, "second digit")
        ace_png_visual.assert_page_png(
            page,
            "agents_session_panel_pending_digit_120x40",
            title="ACE session panel pending shell digit",
        )

        await page.press("0")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].agent_name
                == f"{_AGENT_SESSION_NAME}--phase-10"
            )
        )
        await page.press("apostrophe", "apostrophe")
        await page.wait_for(
            lambda _state: (
                page.app._agents[page.app.current_idx].identity == container_identity
            )
        )
