"""View-strip and view-selection coverage for the Statistics pane."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import statistics_pane_layout as layout
from sase.ace.tui.modals.statistics_pane_data import (
    StatisticsView,
    VIEW_ORDER,
)
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.stats.ranges import StatsRange

from tests.ace.tui._statistics_pane_helpers import (
    assert_statistics_chrome as _assert_statistics_chrome,
    open_statistics as _open_statistics,
    patch_center as _patch_center,
    wait_statistics_settled as _wait_statistics_settled,
)


@pytest.mark.parametrize(
    ("width", "tier"),
    (
        (150, "full"),
        (130, "compact"),
        (120, "compact"),
        (90, "micro"),
        (70, "micro"),
    ),
)
def test_numbered_nine_view_strip_fits_each_statistics_layout_tier(
    width: int,
    tier: str,
) -> None:
    strip = PanelTabStrip(
        layout._VIEW_TABS,
        "overview",
        show_numbers=True,
        uppercase_active=True,
        compact_below=layout._VIEWS_COMPACT_BELOW_WIDTH,
        compact_separator="│",
        micro_below=layout._VIEWS_MICRO_BELOW_WIDTH,
        micro_separator="│",
    )
    strip._tier = tier  # type: ignore[assignment]

    rendered = strip._build_content()

    assert strip._line_width == len(rendered.plain)
    assert strip._line_width <= width
    assert len(strip._tab_ranges) == 9
    assert [
        rendered.plain[start:end].split(maxsplit=1)[0]
        for start, end in strip._tab_ranges.values()
    ] == [f"{number:02d}" for number in range(1, 10)]


async def test_view_cycle_reuses_composite_result_and_updates_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await page.press("right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "runners")

        assert len(calls) == 1
        _assert_statistics_chrome(pane)

        await page.press("right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "projects")
        await _wait_statistics_settled(page, pane)
        assert len(calls) == 2
        assert calls[-1][0] == "projects"
        _assert_statistics_chrome(pane)

        await page.press("right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "providers")
        await _wait_statistics_settled(page, pane)
        assert len(calls) == 3
        assert calls[-1][0] == "providers"
        _assert_statistics_chrome(pane)

        await page.press("left_square_bracket")
        await page.wait_for(lambda _state: pane._view == "projects")
        await _wait_statistics_settled(page, pane)
        assert len(calls) == 4
        assert calls[-1][0] == "projects"
        _assert_statistics_chrome(pane)


async def test_nine_view_keyboard_and_mouse_navigation_share_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        visited = [pane._view]
        for _ in range(len(VIEW_ORDER) - 1):
            await page.press("right_square_bracket")
            visited.append(pane._view)

        assert tuple(visited) == VIEW_ORDER
        await page.wait_for(
            lambda _state: (
                pane._view == "footprint"
                and pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
                and (
                    pane._load_debouncer is None or not pane._load_debouncer.is_pending
                )
            )
        )
        assert calls[-1][0] == "footprint"
        strip = pane.query_one("#statistics-views", PanelTabStrip)
        strip.post_message(PanelTabStrip.TabClicked("runners"))
        await page.wait_for(lambda _state: pane._view == "runners")
        await _wait_statistics_settled(page, pane)

        assert VIEW_ORDER[1] == "runners"
        assert VIEW_ORDER[-1] == "footprint"
        assert strip._active_tab == "runners"
        assert calls[-1][0] in {"footprint", "runners"}


async def test_every_view_selection_path_keeps_heading_tab_rail_and_view_aligned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        assert pane._view == "overview"
        _assert_statistics_chrome(pane)

        await page.press("right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "runners")
        _assert_statistics_chrome(pane)
        assert len(calls) == 1

        await page.press("0", "4")
        await page.wait_for(lambda _state: pane._view == "providers")
        _assert_statistics_chrome(pane)
        assert len(calls) == 1

        strip = pane.query_one("#statistics-views", PanelTabStrip)
        strip.post_message(PanelTabStrip.TabClicked("activity"))
        await page.wait_for(lambda _state: pane._view == "activity")
        _assert_statistics_chrome(pane)
        assert len(calls) == 1

        pane._set_view("overview")
        await page.pause()
        await page.click("#statistics-tile-0")
        await page.wait_for(lambda _state: pane._view == "projects")
        await _wait_statistics_settled(page, pane)
        _assert_statistics_chrome(pane)
        assert len(calls) == 2
        assert calls[-1][0] == "projects"
