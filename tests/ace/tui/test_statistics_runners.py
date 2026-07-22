"""Focused presentation coverage for the Statistics Runners view."""

from __future__ import annotations

from datetime import UTC
from typing import Any

import pytest
from rich.columns import Columns
from rich.console import Console, Group

from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_pane_data import StatisticsViewData
from sase.ace.tui.modals.statistics_pane_runners import (
    _busiest_runner_slices,
    _compress_runner_trend,
    _time_at_or_above_current_limit,
)
from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.ranges import StatsRange
from sase.stats.views import build_statistics_views


def _render_plain(renderable: object, *, width: int = 180) -> str:
    console = Console(width=width, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _runner_result(
    *,
    include_runner_payload: bool = True,
    idle: bool = False,
    launched_runs: int = 0,
    project_filter: str | None = None,
) -> StatisticsViewData:
    selected_range = StatsRange(0, 14_400, "Four hours", "Thu 00:00–04:00 UTC")
    run_payload: dict[str, Any] = {
        "start_ts": 0,
        "end_ts": 14_400,
        "totals": {
            "runs": launched_runs,
            "completed": launched_runs,
            "failed": 0,
        },
    }
    if include_runner_payload:
        if idle:
            runner_payload = {
                "start_ts": 0.0,
                "end_ts": 14_400.0,
                "peak_runners": 0,
                "peak_seconds": 14_400.0,
                "average_runners": 0.0,
                "busy_seconds": 0.0,
                "busy_share": 0.0,
                "runner_seconds": 0.0,
                "distribution": [{"runners": 0, "seconds": 14_400.0, "share": 1.0}],
                "trend": [
                    {
                        "start_ts": 0.0,
                        "end_ts": 14_400.0,
                        "average_runners": 0.0,
                        "peak_runners": 0,
                        "busy_seconds": 0.0,
                        "runner_seconds": 0.0,
                    }
                ],
                "malformed_rows_skipped": 0,
                "invalid_intervals_skipped": 0,
            }
        else:
            runner_payload = {
                "start_ts": 0.0,
                "end_ts": 14_400.0,
                "peak_runners": 4,
                "peak_seconds": 1_800.0,
                "average_runners": 1.625,
                "busy_seconds": 10_800.0,
                "busy_share": 0.75,
                "runner_seconds": 23_400.0,
                "distribution": [
                    {"runners": 0, "seconds": 3_600.0, "share": 0.25},
                    {"runners": 1, "seconds": 3_600.0, "share": 0.25},
                    {"runners": 2, "seconds": 3_600.0, "share": 0.25},
                    {"runners": 3, "seconds": 1_800.0, "share": 0.125},
                    {"runners": 4, "seconds": 1_800.0, "share": 0.125},
                ],
                "trend": [
                    {
                        "start_ts": 0.0,
                        "end_ts": 3_600.0,
                        "average_runners": 0.5,
                        "peak_runners": 1,
                        "busy_seconds": 1_800.0,
                        "runner_seconds": 1_800.0,
                    },
                    {
                        "start_ts": 3_600.0,
                        "end_ts": 7_200.0,
                        "average_runners": 1.5,
                        "peak_runners": 3,
                        "busy_seconds": 3_600.0,
                        "runner_seconds": 5_400.0,
                    },
                    {
                        "start_ts": 7_200.0,
                        "end_ts": 10_800.0,
                        "average_runners": 3.25,
                        "peak_runners": 4,
                        "busy_seconds": 3_600.0,
                        "runner_seconds": 11_700.0,
                    },
                    {
                        "start_ts": 10_800.0,
                        "end_ts": 14_400.0,
                        "average_runners": 1.25,
                        "peak_runners": 3,
                        "busy_seconds": 1_800.0,
                        "runner_seconds": 4_500.0,
                    },
                ],
                "malformed_rows_skipped": 1,
                "invalid_intervals_skipped": 2,
            }
        run_payload["runners"] = runner_payload
    snapshot = ProjectDisplaySnapshot({"widgets": "Widgets"})
    return StatisticsViewData(
        view="runners",
        selected_range=selected_range,
        runtime_group_by="tribe",
        generated_at=10_800.0,
        views=build_statistics_views(
            run_payload,
            {},
            timezone=UTC,
            current_runner_limit=3,
            project_display_snapshot=snapshot,
        ),
        project_filter=project_filter,
        project_display_snapshot=snapshot,
    )


def test_summary_derives_current_limit_comparison_and_surfaces_caveats() -> None:
    result = _runner_result(project_filter="widgets")
    pane = StatisticsPane(auto_load=False)
    pane._project_filter = "widgets"

    summary = pane._runner_summary(result.views.runners, width=120)
    cards = tuple(summary.renderables)
    rendered = _render_plain(summary)
    context = _render_plain(Group(*pane._runner_context(result.views.runners)))

    assert [card.title for card in cards] == [
        "Peak",
        "Average",
        "Busy",
        "Runner time",
        "Global limit now",
    ]
    assert "4 runners" in rendered
    assert "30m00s at peak" in rendered
    assert "1.62 runners" in rendered
    assert "75.0%" in rendered
    assert "3h00m busy" in rendered
    assert "6h30m" in rendered
    assert "1h00m · 25.0%" in rendered
    assert "at/above" in rendered
    assert _time_at_or_above_current_limit(result.views.runners) == (3_600.0, 0.25)
    assert "not project-specific capacity or a historical limit" in context
    assert "Observed peak 4 exceeds today's current global limit 3" in context
    assert "skipped 1 malformed rows and 2 invalid intervals" in context


def test_timeline_uses_fixed_zero_baseline_peak_scale_and_bounded_columns() -> None:
    result = _runner_result()
    pane = StatisticsPane(auto_load=False)

    timeline = pane._runner_timeline(result, width=70)
    rendered = _render_plain(timeline, width=80)
    compressed = _compress_runner_trend(result.views.runners.trend, width=2)

    assert "█ average" in rendered
    assert "◆ peak" in rendered
    assert "─ limit now" in rendered
    assert "fixed 0–4" in rendered
    assert "0└" in rendered
    assert "Thu 00:00 → Thu 03:00 · 4 slices" in rendered
    assert "Thu 00:00–04:00 UTC · Four" in rendered
    assert "hours" in rendered
    assert len(compressed) == 2
    assert compressed[0].average_runners == pytest.approx(1.0)
    assert compressed[0].peak_runners == 3
    assert compressed[1].average_runners == pytest.approx(2.25)
    assert compressed[1].peak_runners == 4


def test_occupancy_contains_every_exact_row_and_current_day_styles() -> None:
    runners = _runner_result().views.runners
    pane = StatisticsPane(auto_load=False)

    rendered = _render_plain(pane._runner_occupancy(runners, width=72))

    assert "0 · idle" in rendered
    assert rendered.count("1h00m") >= 3
    assert rendered.count("25.00%") == 3
    assert rendered.count("12.50%") == 2
    assert "Gold/red rows compare with today's current global limit" in rendered
    assert pane._runner_occupancy_color(0, 3) == "#666666"
    assert pane._runner_occupancy_color(1, 3) == "#87D7FF"
    assert pane._runner_occupancy_color(2, 3) == "#FF87D7"
    assert pane._runner_occupancy_color(3, 3) == "#FFD700"
    assert pane._runner_occupancy_color(4, 3) == "#FF5F5F"


def test_busiest_slices_sort_by_peak_average_then_time() -> None:
    runners = _runner_result().views.runners
    pane = StatisticsPane(auto_load=False)

    ordered = _busiest_runner_slices(runners.trend)
    rendered = _render_plain(pane._runner_busiest_slices(runners))

    assert [slice_.label for slice_ in ordered] == [
        "Thu 02:00",
        "Thu 01:00",
        "Thu 03:00",
        "Thu 00:00",
    ]
    assert rendered.index("Thu 02:00") < rendered.index("Thu 01:00")
    assert rendered.index("Thu 01:00") < rendered.index("Thu 03:00")
    assert "3h15m" in rendered


def test_idle_and_carry_in_payloads_render_even_when_launch_views_are_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for result in (_runner_result(idle=True), _runner_result()):
        assert result.views.empty is True
        assert result.views.runners.available is True
        pane = StatisticsPane(auto_load=False)
        pane._view = "runners"
        pane._last_result = result
        updates: dict[str, object] = {}
        monkeypatch.setattr(
            pane,
            "_update_static",
            lambda selector, content, updates=updates: updates.__setitem__(
                selector, content
            ),
        )
        monkeypatch.setattr(pane, "_set_tiles_visible", lambda _visible: None)

        pane._paint_current_view()
        rendered = _render_plain(updates["#statistics-body"])

        assert "No agent runs recorded" not in rendered
        assert "Concurrency over time" in rendered
    assert "0 · idle" in _render_plain(updates["#statistics-body"])
    assert "100.00%" in _render_plain(
        StatisticsPane(auto_load=False)._runner_occupancy(
            _runner_result(idle=True).views.runners,
            width=72,
        )
    )


def test_missing_runner_payload_has_distinct_recovery_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _runner_result(
        include_runner_payload=False,
        launched_runs=2,
        project_filter="widgets",
    )
    assert result.views.empty is False
    assert result.views.runners.available is False
    pane = StatisticsPane(auto_load=False)
    pane._view = "runners"
    pane._last_result = result
    updates: dict[str, object] = {}
    monkeypatch.setattr(
        pane,
        "_update_static",
        lambda selector, content: updates.__setitem__(selector, content),
    )
    monkeypatch.setattr(pane, "_set_tiles_visible", lambda _visible: None)

    pane._paint_current_view()
    rendered = _render_plain(updates["#statistics-body"])

    assert "Runners unavailable" in rendered
    assert (
        "No runner occupancy snapshot is available for Thu 00:00–04:00 UTC" in rendered
    )
    assert "older or partial" in rendered
    assert "No agent runs recorded" not in rendered
    assert "Press p/P to clear the Widgets project filter." in rendered


def test_wide_and_narrow_compositions_switch_without_changing_data() -> None:
    result = _runner_result(launched_runs=4)
    pane = StatisticsPane(auto_load=False)
    pane._runners_stacked = False
    wide = pane._runners_renderable(result)
    pane._runners_stacked = True
    narrow = pane._runners_renderable(result)

    assert any(isinstance(item, Columns) for item in wide.renderables)
    assert any(isinstance(item, Group) for item in narrow.renderables)
    for rendered in (_render_plain(wide), _render_plain(narrow)):
        assert "Occupancy by runner count" in rendered
        assert "Busiest slices" in rendered
        assert "Thu 02:00" in rendered
