"""sase's TUI PNG visual snapshots for Agents deck splits and focus."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.model import DeckId
from sase.feature_flags import override_flags
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _deck_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-decks",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 9, 24, 10, 0, 0),
        stop_time=datetime(2026, 9, 24, 10, 7, 30),
        raw_suffix="20260924-100000-decks",
        agent_name="decker",
        llm_provider="codex",
        model="gpt-5",
        response_path="/workspace/sase/artifacts/visual-decks/response.md",
    )


def _reply_agent(tmp_path: Path) -> Agent:
    """Build a fixture agent whose Main deck has Context and Reply cards."""
    artifacts_dir = tmp_path / "visual-decks-artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_xprompt.md").write_text(
        "Launch visual decks\n", encoding="utf-8"
    )
    (artifacts_dir / "01_prompt.md").write_text(
        "Visual prompt body\n", encoding="utf-8"
    )
    response_path = artifacts_dir / "response.md"
    response_path.write_text("Visual response body\n", encoding="utf-8")
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-decks",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 9, 24, 10, 0, 0),
        stop_time=datetime(2026, 9, 24, 10, 7, 30),
        raw_suffix="20260924-100000-decks",
        agent_name="decker",
        llm_provider="codex",
        model="gpt-5",
        artifacts_dir=str(artifacts_dir),
        response_path=str(response_path),
    )


async def _goto_agents(page: AcePage, count: int) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.expect_state("agent_count", count)
    await wait_for_visual_idle(page)


async def test_agents_decks_single_main_context_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_deck_agent()])
    with override_flags(agent_decks=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _goto_agents(page, 1)
            ace_png_visual.assert_page_png(
                page,
                "agents_decks_single_main_context_120x40",
                title="ACE agents decks single Main on Context",
            )


async def test_agents_decks_single_main_reply_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_reply_agent(tmp_path)])
    with override_flags(agent_decks=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _goto_agents(page, 1)
            detail = page.app.query_one("#agent-detail-panel", AgentDetail)
            await wait_for_state(
                page,
                lambda: (
                    set(detail._main_deck_document.card_ids) == {"context", "reply"}
                ),
                description="Main deck has Context and Reply cards",
            )
            await page.press("ctrl+j")
            await wait_for_visual_idle(page)
            assert detail.deck_area.panel(0).main_view.active_card_id == "reply"
            ace_png_visual.assert_page_png(
                page,
                "agents_decks_single_main_reply_120x40",
                title="ACE agents decks single Main on Reply",
            )


async def test_agents_decks_single_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    with override_flags(agent_decks=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _goto_agents(page, 0)
            ace_png_visual.assert_page_png(
                page,
                "agents_decks_single_empty_120x40",
                title="ACE agents decks single empty state",
            )


async def test_agents_decks_top_bottom_focus_bottom_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_deck_agent()])
    with override_flags(agent_decks=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _goto_agents(page, 1)
            await page.press("backslash")
            await wait_for_visual_idle(page)
            ace_png_visual.assert_page_png(
                page,
                "agents_decks_top_bottom_focus_bottom_120x40",
                title="ACE agents decks top-bottom focus bottom",
            )


async def test_agents_decks_left_right_ratio_70_focus_left_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_deck_agent()])
    with override_flags(agent_decks=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _goto_agents(page, 1)
            await page.press("vertical_line")
            await wait_for_visual_idle(page)
            await page.press("ctrl+f")
            await wait_for_visual_idle(page)
            await page.press("right_curly_bracket")
            await wait_for_visual_idle(page)
            ace_png_visual.assert_page_png(
                page,
                "agents_decks_left_right_ratio_70_focus_left_120x40",
                title="ACE agents decks left-right ratio 70 focus left",
            )


async def test_agents_decks_context_reply_no_files_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_reply_agent(tmp_path)])
    with override_flags(agent_decks=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _goto_agents(page, 1)
            detail = page.app.query_one("#agent-detail-panel", AgentDetail)
            await wait_for_state(
                page,
                lambda: (
                    set(detail._main_deck_document.card_ids) == {"context", "reply"}
                ),
                description="Main deck has Context and Reply cards",
            )
            # Force known no-files/no-tools so the new panel duplicates Main.
            detail.deck_area.panel(0)._availability = {
                DeckId.MAIN: DeckAvailability(True, 2),
                DeckId.FILES: DeckAvailability(False, 0),
                DeckId.TOOLS: DeckAvailability(False, 0),
            }
            await page.press("vertical_line")
            await wait_for_visual_idle(page)
            panel0 = detail.deck_area.panel(0)
            panel1 = detail.deck_area.panel(1)
            assert panel1.deck is DeckId.MAIN
            assert panel0.main_view.active_card_id != panel1.main_view.active_card_id
            ace_png_visual.assert_page_png(
                page,
                "agents_decks_context_reply_no_files_120x40",
                title="ACE agents decks context reply no files",
            )


async def test_agents_decks_collapsed_single_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_deck_agent()])
    with override_flags(agent_decks=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _goto_agents(page, 1)
            detail = page.app.query_one("#agent-detail-panel", AgentDetail)
            await page.press("ctrl+s")
            await wait_for_visual_idle(page)
            assert detail.is_nodes_collapsed is True
            ace_png_visual.assert_page_png(
                page,
                "agents_decks_collapsed_single_120x40",
                title="ACE agents decks collapsed node panel single",
            )


async def test_agents_decks_collapsed_split_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_deck_agent()])
    with override_flags(agent_decks=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _goto_agents(page, 1)
            detail = page.app.query_one("#agent-detail-panel", AgentDetail)
            await page.press("vertical_line")
            await wait_for_visual_idle(page)
            await page.press("ctrl+s")
            await wait_for_visual_idle(page)
            assert detail.is_nodes_collapsed is True
            ace_png_visual.assert_page_png(
                page,
                "agents_decks_collapsed_split_120x40",
                title="ACE agents decks collapsed node panel split",
            )


async def test_agents_decks_zoomed_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_deck_agent()])
    with override_flags(agent_decks=True):
        async with AcePage(query='"visual"', patches=patches()) as page:
            await _goto_agents(page, 1)
            detail = page.app.query_one("#agent-detail-panel", AgentDetail)
            await page.press("vertical_line")
            await wait_for_visual_idle(page)
            # Focus back to the Main panel so the zoom shows deck content.
            await page.press("ctrl+f")
            await wait_for_visual_idle(page)
            assert detail.deck_area.focused_panel().deck is DeckId.MAIN
            await page.press("Z")
            await wait_for_visual_idle(page)
            assert detail.is_deck_zoomed is True
            ace_png_visual.assert_page_png(
                page,
                "agents_decks_zoomed_120x40",
                title="ACE agents decks zoomed focused panel",
            )
