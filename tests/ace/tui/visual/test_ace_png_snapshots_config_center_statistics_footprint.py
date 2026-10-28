"""ACE PNG snapshots for the Statistics Footprint view."""

from __future__ import annotations

import pytest
from textual.containers import VerticalScroll
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_config_center_statistics_png_snapshot_shared import (
    open_statistics_modal,
    patch_siblings,
    patch_statistics_footprint,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_config_center_statistics_footprint_map_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_footprint(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = "textual-dark"
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        await page.wait_for(lambda _state: pane._footprint_card is not None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_map_120x40",
            title="ACE SASE Admin Center — Statistics Footprint map",
        )


async def test_config_center_statistics_footprint_cold_card_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_footprint(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        page.app.theme = "textual-light"
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        await page.press("g")
        await page.wait_for(
            lambda _state: (
                pane._footprint_lens == "cold"
                and pane._last_result is not None
                and pane._last_result.footprint_lens == "cold"
                and not pane._loading
            )
        )
        pane._footprint_selected_index = 1
        pane._paint_current_view()
        pane._schedule_footprint_card()
        await page.wait_for(
            lambda _state: pane._footprint_card_for == ("feature", "cli:bead.close")
        )
        scroll = pane.query_one("#statistics-body-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_cold_card_light_90x30",
            title="ACE SASE Admin Center — Statistics Footprint candidate card",
        )


async def test_config_center_statistics_footprint_finder_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_footprint(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = "textual-dark"
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        await page.wait_for(lambda _state: pane._footprint_card is not None)
        await page.press("slash")
        await page.expect_modal("StatisticsFootprintFinderModal")
        await page.press(
            "v",
            "i",
            "e",
            "w",
            "colon",
            "s",
            "t",
            "a",
            "t",
            "s",
            "full_stop",
            "f",
            "o",
            "o",
            "t",
            "p",
            "r",
            "i",
            "n",
            "t",
        )
        await page.wait_for(
            lambda _state: (
                page.app.screen.query_one(
                    "#statistics-footprint-finder-list", OptionList
                ).option_count
                == 1
            )
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_finder_120x40",
            title="ACE SASE Admin Center — Statistics Footprint feature finder",
        )


async def test_config_center_statistics_footprint_area_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_footprint(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        page.app.theme = "textual-light"
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        pane._footprint_selected_index = 1
        pane.action_open_row()
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint_area == "tui.statistics"
                and not pane._loading
            )
        )
        await page.wait_for(
            lambda _state: (
                pane._footprint_card_for == ("feature", "tui:statistics.cycle_range")
            )
        )
        scroll = pane.query_one("#statistics-body-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)
        scroll.scroll_to(y=max(0, scroll.max_scroll_y - 7), animate=False)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_area_narrow_light_90x30",
            title="ACE SASE Admin Center — Statistics Footprint area",
        )


async def test_config_center_statistics_footprint_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_footprint(monkeypatch, empty=True)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_empty_120x40",
            title="ACE SASE Admin Center — Statistics Footprint empty",
        )


async def test_config_center_statistics_footprint_all_unknown_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_footprint(monkeypatch, all_unknown=True)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        page.app.theme = "textual-light"
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        await page.wait_for(lambda _state: pane._footprint_card is not None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_all_unknown_light_90x30",
            title="ACE SASE Admin Center — Statistics Footprint all unknown",
        )
