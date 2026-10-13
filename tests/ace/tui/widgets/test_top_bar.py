"""Fits for the top-bar indicator cluster density."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.widgets.tab_bar import TabBar
from sase.ace.tui.widgets.top_bar import TopBar, TopBarIndicators


class _FitApp(App[None]):
    def compose(self) -> ComposeResult:
        with TopBar():
            yield TabBar(id="tab-bar")
            yield TopBarIndicators(id="top-bar-indicators")


@pytest.mark.asyncio
async def test_fit_keeps_full_density_when_width_unknown() -> None:
    """A pre-layout fit must not stick compact density.

    Regression: ``fit_top_bar_indicators`` ran on mount with a zero region
    width, picked compact (dropping the ``inbox:`` group label), and no
    later fit revisited the choice when the size never changed — so loaded
    CI runners captured the compact frame while local runs stayed full.
    """
    app = _FitApp()
    async with app.run_test() as pilot:
        bar = app.query_one(TopBar)
        cluster = app.query_one(TopBarIndicators)
        assert cluster.density == "full"
        bar.styles.width = 0
        await pilot.pause()
        assert cluster.density == "full"
        assert all(group.density == "full" for group in cluster.groups())


@pytest.mark.asyncio
async def test_fit_still_compacts_a_genuinely_narrow_bar() -> None:
    """Narrow bars keep compact density; the guard is not always-full."""
    app = _FitApp()
    async with app.run_test() as pilot:
        bar = app.query_one(TopBar)
        cluster = app.query_one(TopBarIndicators)
        bar.styles.width = 10
        await pilot.pause()
        assert cluster.density == "compact"
        bar.styles.width = "100%"
        await pilot.pause()
        assert cluster.density == "full"
