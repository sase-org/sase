"""Hover tooltip coverage for reusable panel tabs."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.widgets.panel_tab_strip import PanelTab, PanelTabStrip


def _tabs_with_descriptions() -> tuple[PanelTab, ...]:
    return (
        PanelTab("one", "One", "cyan", shortcut="1", description="Tab one."),
        PanelTab(
            "two",
            "Two",
            "magenta",
            icon="🔥",
            shortcut="2",
            description="Tab two.",
        ),
        PanelTab("three", "Three", "green", shortcut="3", description="Tab three."),
    )


def _tabs_without_descriptions() -> tuple[PanelTab, ...]:
    return (
        PanelTab("one", "One", "cyan", shortcut="1"),
        PanelTab("two", "Two", "magenta", shortcut="2"),
    )


class _TooltipApp(App[None]):
    def __init__(self, tabs: tuple[PanelTab, ...]) -> None:
        self._tabs = tabs
        super().__init__()

    def compose(self) -> ComposeResult:
        yield PanelTabStrip(self._tabs, "one", show_numbers=True, id="tabs")


async def test_hover_over_tab_sets_tooltip_to_its_description() -> None:
    async with _TooltipApp(_tabs_with_descriptions()).run_test(size=(60, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", PanelTabStrip)
        start, _ = strip._tab_ranges["three"]
        content_width = max(0, int(strip.size.width))
        center_pad = max(0, (content_width - strip._line_width) // 2)

        await pilot.hover(strip, offset=(center_pad + start + 1, 0))
        await pilot.pause()

        assert strip.tooltip == "Tab three."


async def test_hover_between_tabs_clears_tooltip() -> None:
    async with _TooltipApp(_tabs_with_descriptions()).run_test(size=(60, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", PanelTabStrip)
        start, _ = strip._tab_ranges["two"]
        content_width = max(0, int(strip.size.width))
        center_pad = max(0, (content_width - strip._line_width) // 2)

        # Land in the " │ " separator that precedes "two", not on a tab.
        await pilot.hover(strip, offset=(center_pad + start - 2, 0))
        await pilot.pause()

        assert strip.tooltip is None


async def test_leaving_the_strip_clears_the_tooltip() -> None:
    async with _TooltipApp(_tabs_with_descriptions()).run_test(size=(60, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", PanelTabStrip)
        start, _ = strip._tab_ranges["one"]
        content_width = max(0, int(strip.size.width))
        center_pad = max(0, (content_width - strip._line_width) // 2)

        await pilot.hover(strip, offset=(center_pad + start + 1, 0))
        await pilot.pause()
        assert strip.tooltip == "Tab one."

        # Hover somewhere below the strip so the pointer leaves it.
        await pilot.hover(None, offset=(0, strip.region.bottom + 1))
        await pilot.pause()

        assert strip.tooltip is None


async def test_tabs_without_any_description_leave_tooltip_untouched() -> None:
    async with _TooltipApp(_tabs_without_descriptions()).run_test(
        size=(60, 5)
    ) as pilot:
        strip = pilot.app.query_one("#tabs", PanelTabStrip)
        strip.tooltip = "unrelated"
        start, _ = strip._tab_ranges["two"]
        content_width = max(0, int(strip.size.width))
        center_pad = max(0, (content_width - strip._line_width) // 2)

        await pilot.hover(strip, offset=(center_pad + start + 1, 0))
        await pilot.pause()
        assert strip.tooltip == "unrelated"

        await pilot.hover(None, offset=(0, strip.region.bottom + 1))
        await pilot.pause()
        assert strip.tooltip == "unrelated"


@pytest.mark.parametrize("tier", ("full", "compact", "micro"))
def test_hit_test_is_cell_accurate_at_every_tier(tier: str) -> None:
    tabs = (
        PanelTab(
            "one",
            "One",
            "cyan",
            compact_label="1",
            micro_label="1",
            icon="🔥",
            shortcut="1",
            description="Tab one.",
        ),
        PanelTab(
            "two",
            "Two",
            "magenta",
            compact_label="2",
            micro_label="2",
            icon="◉",
            shortcut="2",
            description="Tab two.",
        ),
    )
    strip = PanelTabStrip(
        tabs,
        "one",
        show_numbers=True,
        compact_below=100,
        micro_below=100,
    )
    strip._tier = tier  # type: ignore[assignment]
    strip._build_content()

    start, end = strip._tab_ranges["two"]
    assert strip._tab_id_at(start) == "two"
    assert strip._tab_id_at(end - 1) == "two"
    assert strip._tab_id_at(end) != "two"
