"""ACE TUI PNG visual snapshot coverage for Agents-tab file zoom modals."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_zoom_fixtures import (
    pin_zoom_file_header,
    wait_for_zoom_content,
    zoom_agent,
    zoom_multi_file_agent,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agents_file_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_zoom_file_header(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=[zoom_agent(tmp_path)])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        await wait_for_zoom_content(
            page,
            "build_zoom_summary",
            scroll_selector="#zoom-file-scroll",
        )

        ace_png_visual.assert_page_png(
            page,
            "agents_file_zoom_modal_120x40",
            title="ACE agents file zoom modal",
        )


async def test_agents_multi_file_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_zoom_file_header(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=[zoom_multi_file_agent(tmp_path)])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        await wait_for_zoom_content(
            page,
            "FILES (3)",
            scroll_selector="#zoom-file-scroll",
        )

        assert_page_svg_contains(page, "FILES (3)")
        assert_page_svg_contains(page, "review_notes.md")
        assert_page_svg_contains(page, "implementation_plan.md")
        ace_png_visual.assert_page_png(
            page,
            "agents_multi_file_zoom_modal_120x40",
            title="ACE agents multi-file zoom modal",
        )


async def test_agents_file_zoom_search_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_zoom_file_header(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=[zoom_agent(tmp_path)])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        await wait_for_zoom_content(
            page,
            "build_zoom_summary",
            scroll_selector="#zoom-file-scroll",
        )
        await page.press("slash", "s", "u", "m", "m", "a", "r", "y")

        command = page.app.screen.query_one("#zoom-search-command", Static)
        search_scroll = page.app.screen.query_one("#zoom-search-scroll", VerticalScroll)
        await wait_for_state(
            page,
            lambda: "/summary" in command.render().plain and search_scroll.has_focus,
            description="zoom search query and search-scroll focus",
        )
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_file_zoom_search_120x40",
            title="ACE agents file zoom search",
        )
