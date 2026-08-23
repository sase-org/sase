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
    _assert_statistics_chrome,
    _open_statistics,
    _patch_center,
)


@pytest.mark.parametrize(
    ("width", "tier"),
    (
        (130, "full"),
        (120, "compact"),
        (90, "compact"),
        (70, "micro"),
    ),
)
def test_numbered_eight_view_strip_fits_each_statistics_layout_tier(
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
    assert len(strip._tab_ranges) == 8
    assert [
        rendered.plain[start:end].split(maxsplit=1)[0]
        for start, end in strip._tab_ranges.values()
    ] == [f"{number:02d}" for number in range(1, 9)]


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
        assert len(calls) == 1
        _assert_statistics_chrome(pane)

        await page.press("right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "providers")
        await page.press("left_square_bracket")
        await page.wait_for(lambda _state: pane._view == "projects")
        assert len(calls) == 1


async def test_eight_view_keyboard_and_mouse_navigation_share_order(
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
                pane._view == "perf"
                and pane._last_result is not None
                and pane._last_result.perf is not None
                and not pane._loading
                and (
                    pane._load_debouncer is None or not pane._load_debouncer.is_pending
                )
            )
        )
        assert len(calls) == 2
        strip = pane.query_one("#statistics-views", PanelTabStrip)
        strip.post_message(PanelTabStrip.TabClicked("runners"))
        await page.wait_for(lambda _state: pane._view == "runners")

        assert VIEW_ORDER[1] == "runners"
        assert VIEW_ORDER[-1] == "perf"
        assert strip._active_tab == "runners"
        assert len(calls) == 2


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
        _assert_statistics_chrome(pane)
        assert len(calls) == 1
