"""Statistics pane coverage for Footprint actor, lens, and area navigation."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from tests.ace.tui._statistics_pane_helpers import (
    _open_statistics,
    _patch_center,
    _render_plain,
    _wait_statistics_settled,
)


async def test_footprint_view_cycles_actor_and_lens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("footprint")
        await _wait_statistics_settled(page, pane)

        assert pane._footprint_lens == "map"
        assert pane._footprint_actor == "you"
        assert pane.query_one("#statistics-tiles").display is True
        assert _scope_actor(pane) == "You"
        report = pane._last_result.footprint if pane._last_result is not None else None
        assert report is not None
        assert report["header"]["actor"] == "you"
        assert "PREVIEW" in _render_plain(pane._view_renderable(pane._last_result))

        await page.press("a")
        await _wait_statistics_settled(page, pane)
        assert pane._footprint_actor == "agents"
        assert _scope_actor(pane) == "Agents"
        assert pane._last_result is not None
        assert pane._last_result.footprint["header"]["actor"] == "agents"

        await page.press("g")
        await _wait_statistics_settled(page, pane)
        assert pane._footprint_lens == "cold"
        assert pane._last_result is not None
        assert pane._last_result.footprint_lens == "cold"


async def test_footprint_rows_drill_into_and_back_out_of_an_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("footprint")
        await _wait_statistics_settled(page, pane)

        assert pane._footprint_items()[0]["area"] == "cli.bead"
        await page.press("j")
        assert pane._footprint_selected_index == 1
        assert pane._footprint_items()[pane._footprint_selected_index]["area"] == (
            "tui.statistics"
        )

        await page.press("enter")
        await _wait_statistics_settled(page, pane)
        assert pane._footprint_area == "tui.statistics"
        assert pane._last_result is not None
        assert pane._last_result.footprint_area == "tui.statistics"
        assert "tui:statistics.cycle_range" in _render_plain(
            pane._view_renderable(pane._last_result)
        )

        await page.press("backspace")
        await _wait_statistics_settled(page, pane)
        assert pane._footprint_area is None
        assert "Surface map" in _render_plain(pane._view_renderable(pane._last_result))


def _scope_actor(pane: StatisticsPane) -> str:
    text = pane.query_one("#statistics-scope-actor", Static).render().plain
    return text.split("Actor ", 1)[-1].strip()


def test_footprint_empty_and_unmeasured_states_are_explicit() -> None:
    from dataclasses import replace

    from tests.ace.tui._statistics_pane_helpers import _result

    pane = StatisticsPane(auto_load=False)
    pane._view = "footprint"
    result = _result("footprint", pane._range, empty=True)
    empty = _render_plain(pane._view_renderable(result))
    assert "No Footprint catalog has been ingested yet" in empty
    assert "cannot distinguish untracked features from no recorded use" in empty

    populated_result = _result("footprint", pane._range)
    pane._last_result = populated_result
    pane._footprint_lens = "map"
    populated = _render_plain(pane._view_renderable(populated_result))
    assert "mobile" in populated
    assert "? not measured" in populated

    pane._footprint_lens = "coverage"
    coverage_result = replace(populated_result, footprint_lens="coverage")
    coverage = _render_plain(pane._view_renderable(coverage_result))
    assert "cli" in coverage and "dropped 1" in coverage
    assert "tui" in coverage and "torn 1" in coverage
