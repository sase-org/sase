"""Focused presentation coverage for Statistics legends and recovery states."""

from __future__ import annotations

import pytest
from rich.console import Console

from sase.ace.testing import AcePage
from sase.ace.tui.keymaps import StatisticsPaneKeymaps
from sase.ace.tui.modals.statistics_pane import (
    OVERVIEW_TILE_TARGETS,
    StatisticsPane,
)
from sase.ace.tui.modals.statistics_pane_data import (
    VIEW_ORDER,
    StatisticsView,
)
from sase.ace.tui.modals.statistics_pane_legends import VIEW_LEGENDS
from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.query import RuntimeGroupBy
from sase.stats.ranges import StatsRange

from tests.ace.tui._statistics_pane_helpers import (
    _open_statistics,
    _patch_center,
    _result,
)


def _render_plain(renderable: object) -> str:
    console = Console(width=500, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_legends_exhaustively_cover_views_with_single_line_copy() -> None:
    assert set(VIEW_LEGENDS) == set(VIEW_ORDER)
    for view in VIEW_ORDER:
        entries = VIEW_LEGENDS[view]
        assert entries
        assert all(entry.term.strip() and entry.meaning.strip() for entry in entries)
        assert all("\n" not in entry.term + entry.meaning for entry in entries)
        note = StatisticsPane._legend_note(view)
        assert note.plain
        assert "\n" not in note.plain
        assert all(f"{entry.term} = {entry.meaning}" in note.plain for entry in entries)


def test_view_renderables_include_verified_metric_definitions() -> None:
    pane = StatisticsPane(auto_load=False)
    result = _result(pane._view, pane._range, pane._runtime_group_by)

    expected = {
        "overview": "Success = completed ÷ finished runs",
        "runs": "Outcome share = share of finished runs",
        "runners": "Average = runner-seconds ÷ analyzed wall time",
        "projects": "Success = completed ÷ all runs",
        "providers": "Avg runtime = mean among runs with a valid finish/stop duration",
        "runtime": "In progress = excluded from duration math",
        "activity": "Agents = distinct agent names that used the skill or memory",
        "plans_questions": (
            "(all projects) = global durable activity the project filter cannot scope"
        ),
    }
    for view in VIEW_ORDER:
        pane._view = view
        assert expected[view] in _render_plain(pane._view_renderable(result))


def test_empty_state_names_range_and_omits_irrelevant_filter_action() -> None:
    pane = StatisticsPane(
        auto_load=False,
        keymaps=StatisticsPaneKeymaps(cycle_range="f10"),
    )
    result = _result(
        pane._view,
        pane._range,
        pane._runtime_group_by,
        empty=True,
    )

    rendered = _render_plain(pane._empty_state_renderable(result))

    assert f"No agent runs recorded in {pane._range.display_label}." in rendered
    assert "Press f10 to widen the range." in rendered
    assert "clear" not in rendered


def test_empty_state_names_filtered_project_and_effective_clear_key() -> None:
    project_key = "gh_acme__widgets"
    pane = StatisticsPane(
        auto_load=False,
        keymaps=StatisticsPaneKeymaps(
            cycle_project_filter="f7",
            cycle_project_filter_reverse="f8",
        ),
    )
    result = _result(
        pane._view,
        pane._range,
        pane._runtime_group_by,
        empty=True,
        project_filter=project_key,
        project_display_snapshot=ProjectDisplaySnapshot({project_key: "widgets"}),
    )

    rendered = _render_plain(pane._empty_state_renderable(result))

    assert "Press f7/f8 to clear the widgets project filter." in rendered
    assert project_key not in rendered


def test_error_state_uses_effective_refresh_key() -> None:
    pane = StatisticsPane(
        auto_load=False,
        keymaps=StatisticsPaneKeymaps(refresh="f6"),
    )

    rendered = _render_plain(pane._error_state_renderable("query failed"))

    assert "query failed" in rendered
    assert "Press f6 to retry." in rendered


def test_overview_tile_mapping_is_complete() -> None:
    assert OVERVIEW_TILE_TARGETS == (
        ("Agents Run", "runs"),
        ("Success Rate", "runs"),
        ("Commits", "runs"),
        ("Plans Proposed", "plans_questions"),
        ("Questions", "plans_questions"),
    )


async def test_overview_tile_click_uses_set_view_without_loading_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        await page.click("#statistics-tile-0")
        await page.wait_for(lambda _state: pane._view == "runs")

        assert len(calls) == 1
