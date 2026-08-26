"""ACE TUI PNG visual snapshot coverage for Agents-tab waiting-agent rows."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    assert_page_svg_styled_text_contains,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_zoom_fixtures import (
    wait_for_zoom_content,
    waiting_tribe_agents,
    waiting_unknown_agents,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agents_waiting_missing_target_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.models.agent_wait_beads import _WAIT_BEAD_STATUS_CACHE

    _WAIT_BEAD_STATUS_CACHE.clear()
    _WAIT_BEAD_STATUS_CACHE.set(("sase", "run-bead"), "in_progress")
    _WAIT_BEAD_STATUS_CACHE.set(("sase", "done-bead"), "closed")
    _WAIT_BEAD_STATUS_CACHE.set(("sase", "open-bead"), "open")
    try:
        patch_startup_loaders(
            monkeypatch,
            agents=waiting_unknown_agents(),
        )

        async with AcePage(query='"wait-unknown"', patches=patches()) as page:
            await wait_for_startup(page)
            await page.press("shift+tab")
            await page.expect_state("tab", "agents")
            await page.expect_state("agent_count", 4)
            await wait_for_svg_contains(page, "wait-unknown")
            await wait_for_visual_idle(page)

            assert_page_svg_styled_text_contains(page, "WAITING ✗1 ▶1 ◐1 ✓1 ●1 ?1 ○1")
            assert_page_svg_styled_text_contains(page, "?1 ○1")
            assert_page_svg_styled_text_contains(page, "▶1")
            assert_page_svg_styled_text_contains(page, "◐1")
            assert_page_svg_contains(page, "Wait:")
            assert_page_svg_contains(page, "[agents]")
            assert_page_svg_contains(page, "[beads]")
            assert_page_svg_contains(page, "coder")
            assert_page_svg_contains(page, "builder")
            assert_page_svg_contains(page, "reviewer")
            assert_page_svg_contains(page, "✓")
            assert_page_svg_contains(page, "▶")
            assert_page_svg_contains(page, "✗")
            assert_page_svg_contains(page, "?")
            ace_png_visual.assert_page_png(
                page,
                "agents_waiting_missing_target_row_120x40",
                title="ACE agents missing wait target row and detail",
            )
    finally:
        _WAIT_BEAD_STATUS_CACHE.clear()


async def test_agents_waiting_tribe_target_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=waiting_tribe_agents(),
    )

    async with AcePage(query='"wait-tribe"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 2)
        await wait_for_svg_contains(page, "@epic")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "WAITING")
        assert_page_svg_contains(page, "Wait:")
        assert_page_svg_contains(page, "[tribes]")
        assert_page_svg_contains(page, "@epic")
        assert_page_svg_contains(page, "epic.builder")
        assert_page_svg_contains(page, "▶")
        assert "WAITING ?" not in page.export_svg(title="tribe wait assertion")
        ace_png_visual.assert_page_png(
            page,
            "agents_waiting_tribe_target_row_120x40",
            title="ACE agents pending tribe wait row and detail",
        )


async def test_agents_waiting_unknown_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=waiting_unknown_agents(),
    )

    async with AcePage(query='"wait-unknown"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)
        await page.press("p")
        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        await wait_for_zoom_content(
            page,
            "ghost",
            scroll_selector="#zoom-metadata-scroll",
        )

        assert_page_svg_contains(page, "Wait:")
        assert_page_svg_contains(page, "coder")
        assert_page_svg_contains(page, "builder")
        assert_page_svg_contains(page, "reviewer")
        assert_page_svg_contains(page, "ghost")
        assert_page_svg_contains(page, "✓")
        assert_page_svg_contains(page, "▶")
        assert_page_svg_contains(page, "✗")
        assert_page_svg_contains(page, "?")
        ace_png_visual.assert_page_png(
            page,
            "agents_waiting_unknown_zoom_modal_120x40",
            title="ACE agents waiting unknown zoom modal",
            max_diff_pixels=10_000,
            max_material_diff_pixels=0,
        )
