"""Semantic layout waits for top-bar indicator density in PNG fixtures."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.tab_bar import TabBar
from sase.ace.tui.widgets.top_bar import TopBar, TopBarIndicators
from sase.ace.tui.widgets.top_bar_group import (
    TOP_BAR_MIN_GAP,
    TopBarDensity,
    choose_top_bar_density,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import wait_for_visual_idle


async def wait_for_top_bar_density(
    page: AcePage, *, expected: TopBarDensity | None = None
) -> TopBarDensity:
    """Wait for the density chosen by the laid-out tab and indicator geometry.

    ``expected`` is an assertion about a fixture's intended layout, not a
    density override. The production fit rule remains the source of truth.
    """
    top_bar = page.app.query_one(TopBar)
    tab_bar = page.app.query_one("#tab-bar", TabBar)
    cluster = page.app.query_one("#top-bar-indicators", TopBarIndicators)

    def geometry() -> tuple[int, int, int, int, TopBarDensity] | None:
        try:
            width = int(top_bar.region.width)
            tab_cells = int(tab_bar.content_cells)
            full_cells = int(cluster.full_cells)
            groups_ready = len(cluster.groups()) == 6
        except Exception:
            return None
        if width <= 0 or tab_cells <= 0 or full_cells <= 0 or not groups_ready:
            return None
        free_cells = max(0, width - tab_cells - TOP_BAR_MIN_GAP)
        fit = choose_top_bar_density(free_cells, full_cells=full_cells)
        return width, tab_cells, free_cells, full_cells, fit

    def density_matches_geometry() -> bool:
        measured = geometry()
        return measured is not None and cluster.density == measured[4]

    await page.wait_for(
        lambda _state: density_matches_geometry(),
        timeout=15.0,
    )
    await wait_for_visual_idle(page)
    measured = geometry()
    assert measured is not None, "top-bar geometry was unavailable after layout"
    width, tab_cells, free_cells, full_cells, fit = measured
    assert cluster.density == fit, (
        "top-bar density did not match its available geometry: "
        f"density={cluster.density}, fit={fit}, width={width}, "
        f"tab_cells={tab_cells}, free_cells={free_cells}, "
        f"full_cells={full_cells}"
    )
    if expected is not None:
        assert fit == expected, (
            "fixture's expected top-bar density does not fit its final geometry: "
            f"expected={expected}, fit={fit}, width={width}, "
            f"tab_cells={tab_cells}, free_cells={free_cells}, "
            f"full_cells={full_cells}"
        )
    return fit


__all__ = ["wait_for_top_bar_density"]
