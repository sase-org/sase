"""sase's TUI PNG visual snapshots for the Agents deck picker."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import AgentDetail
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.visual.test_ace_png_snapshots_agents_decks import (
    _goto_agents,
    _reply_agent,
)

pytestmark = pytest.mark.visual


async def test_agents_deck_picker_single_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_reply_agent(tmp_path)])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await wait_for_state(
            page,
            lambda: set(detail._main_deck_document.card_ids) == {"context", "reply"},
            description="Main deck has Context and Reply cards",
        )
        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_picker_single_120x40",
            title="ACE agents deck picker over single Main deck",
        )


async def test_agents_deck_picker_split_bottom_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_reply_agent(tmp_path)])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await wait_for_state(
            page,
            lambda: set(detail._main_deck_document.card_ids) == {"context", "reply"},
            description="Main deck has Context and Reply cards",
        )
        await page.press("backslash")
        await wait_for_visual_idle(page)
        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_picker_split_bottom_120x40",
            title="ACE agents deck picker over split with bottom focused",
        )


async def test_agents_deck_picker_left_right_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_reply_agent(tmp_path)])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await wait_for_state(
            page,
            lambda: set(detail._main_deck_document.card_ids) == {"context", "reply"},
            description="Main deck has Context and Reply cards",
        )
        await page.press("vertical_line")
        await wait_for_visual_idle(page)
        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_deck_picker_left_right_120x40",
            title="ACE agents deck picker over left-right split with right focused",
        )
