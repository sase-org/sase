"""Focused presentation coverage for the Statistics Perf view."""

from __future__ import annotations

from typing import Any

import pytest
from rich.columns import Columns
from rich.console import Console, Group
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.statistics_pane import StatisticsPane, _StatTile
from sase.ace.tui.modals.statistics_pane_data import StatisticsViewData
from sase.core.time import format_local
from sase.stats import build_perf_view
from sase.stats.perf_query import PerfGroupBy
from sase.stats.ranges import StatsRange
from tests.ace.tui._statistics_pane_helpers import (
    _open_statistics,
    _patch_center,
    _result,
)
from tests.stats._views_payloads import (
    perf_logs_payload,
    perf_telemetry_payload,
    perf_telemetry_provider_payload,
)


def _render_plain(renderable: object, *, width: int = 180) -> str:
    console = Console(width=width, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _range() -> StatsRange:
    return StatsRange(1_000, 2_000, "span", "Last hour")


def _perf_result(
    *,
    group_by: PerfGroupBy = "subsystem",
    logs: dict[str, Any] | None = None,
    telemetry: dict[str, Any] | None = None,
    empty_runs: bool = False,
    now: float | None = 2_000.0,
    previous_logs: dict[str, Any] | None = None,
    previous_telemetry: dict[str, Any] | None = None,
    selected_range: StatsRange | None = None,
) -> StatisticsViewData:
    resolved_range = _range() if selected_range is None else selected_range
    view = build_perf_view(
        perf_logs_payload() if logs is None else logs,
        perf_telemetry_payload() if telemetry is None else telemetry,
        selected_range=resolved_range,
        previous_perf_payload=previous_logs,
        previous_telemetry_payload=previous_telemetry,
        group_by=group_by,
        now=now,
    )
    return _result(
        "perf",
        resolved_range,
        empty=empty_runs,
        perf=view,
        perf_group_by=group_by,
    )


def _workflow_telemetry() -> dict[str, Any]:
    telemetry = perf_telemetry_payload()
    telemetry["group_by"] = "workflow"
    telemetry["histograms"] = {
        "sase_agent_run_duration_seconds": {
            "p50": {
                "resolution": "raw",
                "series": [{"labels": {"workflow": "review"}, "value": 20.0}],
            },
            "p95": {
                "resolution": "raw",
                "series": [{"labels": {"workflow": "review"}, "value": 50.0}],
            },
            "max": {
                "resolution": "raw",
                "series": [{"labels": {"workflow": "review"}, "value": 70.0}],
            },
        },
        "sase_workflow_duration_seconds": {
            "p50": {
                "resolution": "raw",
                "series": [{"labels": {"workflow": "review"}, "value": 5.0}],
            },
            "p95": {
                "resolution": "raw",
                "series": [{"labels": {"workflow": "review"}, "value": 9.0}],
            },
            "max": {
                "resolution": "raw",
                "series": [{"labels": {"workflow": "review"}, "value": 11.0}],
            },
        },
    }
    telemetry["counters"] = {
        "sase_agent_runs_total": {
            "resolution": "raw",
            "series": [{"labels": {"workflow": "review"}, "value": 4.0}],
        },
        "sase_agent_runs_total:error": {
            "resolution": "raw",
            "series": [{"labels": {"workflow": "review"}, "value": 1.0}],
        },
    }
    return telemetry


def test_populated_perf_renderable_covers_every_panel() -> None:
    result = _perf_result()
    pane = StatisticsPane(auto_load=False)
    pane._view = "perf"
    rendered = _render_plain(pane._perf_renderable(result))
    tiles = _render_plain(Group(*pane._perf_hero_tiles(result, width=24)))

    assert "Startup breakdown" in rendered
    assert "process→mount" in rendered
    assert "visible ready" in rendered
    assert "1.5s" in tiles
    assert "3 sessions" in rendered
    assert "slowest agents" in rendered
    assert format_local(1_900.0, "%b %d %H:%M") in rendered

    assert "Stalls & hitches" in rendered
    stalls = _render_plain(pane._perf_stalls_panel(result.perf, width=80))
    assert "tui_stall" in stalls
    assert "tui_hitch" in stalls
    assert "tui_pump_stall" in stalls
    assert "tui_hitch +5 suppressed" in stalls
    assert "Top context" in rendered
    assert "agents" in rendered
    assert "1 recovery" in rendered
    assert "3.2s" in rendered

    assert "Latency & reliability · By Subsystem" in rendered
    assert "Agent runs" in rendered
    assert "LLM calls" in rendered
    assert "Hooks" in rendered
    assert "Workflows" in rendered
    assert "Axe cycles" in rendered

    assert "Data & instrumentation" in rendered
    assert "Telemetry" in rendered
    assert "enabled" in rendered
    assert "raw" in rendered
    assert "12 raw / 4 5m / 2 1h" in rendered
    assert "git_ops" in rendered
    assert "absent" in rendered
    assert "launch_timing" in rendered
    assert "truncated" in rendered
    assert "1 unreadable" in rendered
    assert "1 unreadable records skipped" in rendered
    assert "Bounded log read truncated older records for: launch_timing" in rendered
    assert "SASE_TUI_PERF off" in rendered
    assert "SASE_TUI_TRACE off" in rendered
    assert "Set SASE_TUI_PERF=1" in rendered

    assert "Startup" in tiles
    assert "Stalls" in tiles
    assert "Launch" in tiles
    assert "Agent p95" in tiles
    assert "LLM p95" in tiles
    assert "450ms" in tiles
    assert "4 launches" in tiles
    assert "2 slow" in tiles
    assert "worst 3.2s" in tiles
    assert "20 runs" in tiles
    assert "err 5%" in tiles
    assert "retry 8%" in tiles
    assert "2m00s" in tiles


def test_hero_tiles_include_delta_and_startup_sparkline() -> None:
    previous_logs = perf_logs_payload()
    previous_logs["startup"]["stages"][2]["summary"]["p50"] = 1.0  # type: ignore[index]
    previous_telemetry = perf_telemetry_payload()
    previous_telemetry["histograms"]["sase_agent_run_duration_seconds"]["p95"] = {  # type: ignore[index]
        "resolution": "raw",
        "series": [{"labels": {}, "value": 80.0}],
    }
    result = _perf_result(
        previous_logs=previous_logs,
        previous_telemetry=previous_telemetry,
    )
    tiles = _render_plain(
        Group(*StatisticsPane(auto_load=False)._perf_hero_tiles(result, width=24))
    )

    assert "↑ 50.0%" in tiles
    assert "previous" in tiles
    assert any(glyph in tiles for glyph in "▁▂▃▄▅▆▇█")


def test_telemetry_disabled_keeps_log_panels_and_names_config_key() -> None:
    result = _perf_result(telemetry={"enabled": False, "group_by": "subsystem"})
    pane = StatisticsPane(auto_load=False)
    rendered = _render_plain(pane._perf_renderable(result))
    tiles = _render_plain(Group(*pane._perf_hero_tiles(result, width=24)))

    assert "Startup breakdown" in rendered
    assert "Stalls & hitches" in rendered
    assert "visible ready" in rendered
    assert "Telemetry is disabled (telemetry.enabled)." in rendered
    assert "disabled" in rendered
    assert "Agent runs" not in rendered
    assert "Telemetry is" in tiles
    assert "disabled" in tiles
    assert "telemetry.enabled" in tiles
    assert "Agent p95" in tiles
    assert "LLM p95" in tiles
    assert "2m00s" not in tiles


def test_missing_logs_render_empty_states_while_telemetry_table_stays() -> None:
    result = _perf_result(logs={})
    pane = StatisticsPane(auto_load=False)
    rendered = _render_plain(pane._perf_renderable(result))
    tiles = _render_plain(Group(*pane._perf_hero_tiles(result, width=24)))

    assert "no samples in range" in rendered
    assert "Startup breakdown" in rendered
    assert "Stalls & hitches" in rendered
    assert "Latency & reliability · By Subsystem" in rendered
    assert "Agent runs" in rendered
    assert "Logs  no coverage entries" in rendered
    assert "no samples in" in tiles
    assert "range" in tiles
    assert "Startup" in tiles
    assert "Stalls" in tiles


def test_absent_log_source_uses_present_false_empty_state() -> None:
    logs = perf_logs_payload()
    logs["startup"] = {"sessions": 0, "stages": [], "visible_ready_series": []}
    for entry in logs["coverage"]:  # type: ignore[union-attr]
        if entry["source"] == "startup":
            entry["present"] = False
            entry["records_in_window"] = 0
    result = _perf_result(logs=logs)
    rendered = _render_plain(StatisticsPane(auto_load=False)._perf_renderable(result))

    assert "No startup log on disk." in rendered
    assert "absent" in rendered


def test_provider_and_workflow_group_modes_change_the_latency_table() -> None:
    pane = StatisticsPane(auto_load=False)
    provider = _render_plain(
        pane._perf_renderable(
            _perf_result(
                group_by="provider",
                telemetry=perf_telemetry_provider_payload(),
            )
        )
    )
    workflow = _render_plain(
        pane._perf_renderable(
            _perf_result(group_by="workflow", telemetry=_workflow_telemetry())
        )
    )

    assert "Latency & reliability · By Provider" in provider
    assert "codex" in provider
    assert "claude" in provider
    assert "800" in provider
    assert "300" in provider
    assert "20.0%" in provider
    assert "Agent runs" not in provider

    assert "Latency & reliability · By Workflow" in workflow
    assert "review" in workflow
    assert "Agent runs" not in workflow


def test_wide_and_narrow_startup_stalls_switch_without_changing_data() -> None:
    result = _perf_result()
    pane = StatisticsPane(auto_load=False)
    pane._perf_stacked = False
    wide = pane._perf_renderable(result)
    pane._perf_stacked = True
    narrow = pane._perf_renderable(result)

    assert any(isinstance(item, Columns) for item in wide.renderables)
    assert any(isinstance(item, Group) for item in narrow.renderables)
    for rendered in (_render_plain(wide), _render_plain(narrow)):
        assert "Startup breakdown" in rendered
        assert "Stalls & hitches" in rendered
        assert "Latency & reliability · By Subsystem" in rendered
        assert "Data & instrumentation" in rendered


def test_empty_agent_runs_still_paint_populated_perf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _perf_result(empty_runs=True)
    assert result.views.empty is True
    assert result.perf is not None
    pane = StatisticsPane(auto_load=False)
    pane._view = "perf"
    pane._last_result = result
    visible: list[bool] = []
    updates: dict[str, object] = {}
    monkeypatch.setattr(pane, "_set_tiles_visible", visible.append)
    monkeypatch.setattr(pane, "_update_heading", lambda: None)
    monkeypatch.setattr(
        pane,
        "_update_static",
        lambda selector, content: updates.__setitem__(selector, content),
    )

    pane._paint_current_view()

    assert visible[-1] is True
    assert "No agent runs recorded" not in _render_plain(updates["#statistics-body"])
    assert "Startup breakdown" in _render_plain(updates["#statistics-body"])
    assert "Startup" in _render_plain(updates["#statistics-tile-0"])
    assert "Agent p95" in _render_plain(updates["#statistics-tile-3"])


def test_missing_perf_snapshot_has_distinct_recovery_guidance() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "perf"
    result = _result("overview", _range())
    rendered = _render_plain(pane._view_renderable(result))

    assert "No Perf snapshot is available." in rendered
    assert "Press r to retry." in rendered
    assert "Global = Perf ignores the project filter" in rendered


def test_all_time_retention_note_appears_in_the_coverage_strip() -> None:
    result = _perf_result(
        logs={},
        telemetry={"enabled": False},
        selected_range=StatsRange(0, 100, "all", "All time"),
    )
    rendered = _render_plain(StatisticsPane(auto_load=False)._perf_renderable(result))

    assert "All time means as far back as retained telemetry and bounded logs go." in (
        rendered
    )


def test_probes_report_enabled_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)
    result = _perf_result(logs={}, telemetry={"enabled": False})
    rendered = _render_plain(StatisticsPane(auto_load=False)._perf_renderable(result))

    assert "SASE_TUI_PERF on" in rendered
    assert "SASE_TUI_TRACE off" in rendered
    assert "Set SASE_TUI_TRACE=1" in rendered


async def test_perf_tiles_are_plain_and_do_not_navigate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        overview_tile = pane.query_one("#statistics-tile-0", Static)
        assert overview_tile.tooltip == "Open Projects"

        pane._set_view("perf")
        await page.wait_for(
            lambda _state: (
                pane._view == "perf"
                and pane._last_result is not None
                and pane._last_result.perf is not None
                and not pane._loading
            )
        )
        tile = pane.query_one("#statistics-tile-0", Static)
        assert isinstance(tile, _StatTile)
        assert tile.tooltip in {None, ""}
        await page.click("#statistics-tile-0")
        await page.pause()
        assert pane._view == "perf"

        pane._set_view("overview")
        await page.pause()
        restored = pane.query_one("#statistics-tile-0", Static)
        assert restored.tooltip == "Open Projects"
