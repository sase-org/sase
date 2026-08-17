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
    result = _result(pane._view, pane._range)

    expected = {
        "overview": (
            "Success = Success Rate tile = completed ÷ finished runs; "
            "Top projects column = completed ÷ all runs"
        ),
        "runners": "Average = runner-seconds ÷ analyzed wall time",
        "projects": "Success = completed ÷ all runs",
        "providers": "Avg runtime = mean among runs with a valid finish/stop duration",
        "activity": "Agents = distinct agent names that used the skill or memory",
        "xprompts": (
            "Scope = launch-boundary references only; workflow step templates excluded"
        ),
        "plans_questions": (
            "Project scope = plans and questions honor the filter; "
            "skills and memories honor it too, shown on the Activity view"
        ),
        "perf": (
            "Global = Perf ignores the project filter; "
            "its sources have no project labels"
        ),
    }
    for view in VIEW_ORDER:
        pane._view = view
        assert expected[view] in _render_plain(pane._view_renderable(result))


def test_empty_agent_runs_still_paint_the_perf_view() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "perf"
    pane._last_result = _result("perf", pane._range, empty=True)
    painted: list[str] = []
    pane._set_tiles_visible = lambda _visible: None  # type: ignore[method-assign]
    pane._update_heading = lambda: None  # type: ignore[method-assign]
    pane._empty_state_renderable = (  # type: ignore[method-assign]
        lambda _result: painted.append("empty") or "empty"
    )
    pane._view_renderable = (  # type: ignore[method-assign]
        lambda _result: painted.append("perf") or "perf"
    )
    pane._update_static = lambda _selector, _content: None  # type: ignore[method-assign]

    pane._paint_current_view()

    assert painted == ["perf"]


def _assert_view_ignores_run_count_empty_state(view: StatisticsView) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = view
    pane._last_result = _result(view, pane._range, runs_empty=True)
    painted: list[str] = []
    pane._set_tiles_visible = lambda _visible: None  # type: ignore[method-assign]
    pane._update_heading = lambda: None  # type: ignore[method-assign]
    pane._empty_state_renderable = (  # type: ignore[method-assign]
        lambda _result: painted.append("empty") or "empty"
    )
    pane._view_renderable = (  # type: ignore[method-assign]
        lambda _result: painted.append(view) or view
    )
    pane._update_static = lambda _selector, _content: None  # type: ignore[method-assign]

    pane._paint_current_view()

    assert painted == [view]


def test_activity_ignores_the_run_count_empty_state() -> None:
    """A window with zero agent runs can still hold log-backed skill/memory data."""
    _assert_view_ignores_run_count_empty_state("activity")


def test_plans_questions_ignores_the_run_count_empty_state() -> None:
    """A window with zero agent runs can still hold log-backed plan/question data."""
    _assert_view_ignores_run_count_empty_state("plans_questions")


def test_overview_still_shows_empty_state_when_no_runs_are_recorded() -> None:
    """overview, projects, and providers stay run-derived empty states."""
    pane = StatisticsPane(auto_load=False)
    pane._view = "overview"
    pane._last_result = _result("overview", pane._range, runs_empty=True)
    painted: list[str] = []
    pane._set_tiles_visible = lambda _visible: None  # type: ignore[method-assign]
    pane._update_heading = lambda: None  # type: ignore[method-assign]
    pane._empty_state_renderable = (  # type: ignore[method-assign]
        lambda _result: painted.append("empty") or "empty"
    )
    pane._view_renderable = (  # type: ignore[method-assign]
        lambda _result: painted.append("overview") or "overview"
    )
    pane._update_static = lambda _selector, _content: None  # type: ignore[method-assign]

    pane._paint_current_view()

    assert painted == ["empty"]


def test_empty_state_message_is_specific_to_the_selected_view() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "activity"
    assert pane._empty_state_message() == "No skill or memory activity recorded"
    pane._view = "plans_questions"
    assert pane._empty_state_message() == "No plans or questions recorded"
    pane._view = "overview"
    assert pane._empty_state_message() == "No agent runs recorded"


def test_empty_state_names_range_and_omits_irrelevant_filter_action() -> None:
    pane = StatisticsPane(
        auto_load=False,
        keymaps=StatisticsPaneKeymaps(cycle_range="f10"),
    )
    result = _result(
        pane._view,
        pane._range,
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
        ("Agents Run", "projects"),
        ("Success Rate", "projects"),
        ("Commits", "projects"),
        ("Plans Proposed", "plans_questions"),
        ("Questions", "plans_questions"),
    )


async def test_overview_tile_click_uses_set_view_without_loading_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        await page.click("#statistics-tile-0")
        await page.wait_for(lambda _state: pane._view == "projects")

        assert len(calls) == 1
