"""ACE PNG snapshots for the Agents Archive list, banners, and parked marker."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.agents_archive import ArchiveList
from tests.ace.tui.visual._ace_agents_archive_png_snapshot_shared import (
    NOW,
    inbox_agent,
    list_history,
    open_archive,
    settle_archive_detail,
    wait_for_svg,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    page_svg_text,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_archive_list_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Day banners, a container, an interrupted row, pulse, and tab marker."""
    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await open_archive(page, list_history())

        assert_page_svg_contains(page, "Agents ◷")
        assert_page_svg_contains(page, "Today")
        assert_page_svg_contains(page, "Yesterday")
        assert_page_svg_contains(page, "⌂ Inbox")
        assert_page_svg_contains(page, "in:archive")
        assert_page_svg_contains(page, "today.done")
        assert_page_svg_contains(page, "WAS")

        # Expand the Yesterday container so member rows join the golden.
        for _ in range(12):
            selected = page.app._agents_archive_view.archive.selected_key
            if selected is not None and selected.startswith("container:"):
                break
            await page.press("j")
        else:
            raise AssertionError("never reached the container summary row")
        await page.press("l")
        await wait_for_svg(page, "clan.alpha")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "clan.alpha")
        assert_page_svg_contains(page, "clan.beta")
        assert "go to PR" not in page_svg_text(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_list_120x40",
            title="ACE Agents Archive list",
        )


async def test_archive_folded_banners_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Folded Yesterday banner keeps Today open; the parked marker survives."""
    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await open_archive(page, list_history())

        # Walk down to the Yesterday banner and fold it.
        archive_list = page.app.query_one("#archive-list", ArchiveList)
        for _ in range(10):
            keys = archive_list.item_keys
            target = keys.index("banner:day:2026-10-09")
            if archive_list.highlighted == target:
                break
            await page.press("j")
        assert archive_list.highlighted == target
        await page.press("h")
        await page.pause()
        # Step back onto a run row: a cursor parked on a banner keeps
        # the last placeholder painted with the reader idle (recorded
        # as a follow-up), which must not leak into the golden.
        await page.press("k")
        await settle_archive_detail(page)
        await wait_for_visual_idle(page)
        text = page_svg_text(page)
        assert "▸" in text and "Yesterday" in text
        assert "clan.alpha" not in text and "clan.beta" not in text
        assert_page_svg_contains(page, "Today")
        assert_page_svg_contains(page, "today.done")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_folded_banners_120x40",
            title="ACE Agents Archive folded banners",
        )


async def test_archive_parked_marker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tab marker stays visible while another main tab is active."""
    patch_startup_loaders(monkeypatch, agents=[inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await open_archive(page, list_history())

        await page.press("shift+tab")
        await page.expect_state("tab", "services")
        await settle_archive_detail(page)
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Agents ◷")
        ace_png_visual.assert_page_png(
            page,
            "agents_archive_parked_marker_120x40",
            title="ACE Agents Archive parked marker",
        )
