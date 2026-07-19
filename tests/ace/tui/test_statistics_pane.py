"""Worker, interaction, and binding coverage for the Statistics tab."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui.keymaps import load_keymap_registry, statistics_help_bindings
from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_pane_data import (
    StatisticsView,
    StatisticsViewData,
)
from sase.stats.query import RuntimeGroupBy
from sase.stats.ranges import StatsRange
from sase.stats.views import build_statistics_views

from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _patch_catalog,
    _patch_other_panes,
)

_NOW = 1_720_268_400.0


def _run_payload(selected_range: StatsRange, group_by: RuntimeGroupBy) -> dict:
    return {
        "start_ts": selected_range.start_ts,
        "end_ts": selected_range.end_ts,
        "runtime_group_by": group_by,
        "bucket_seconds": 86_400,
        "totals": {
            "runs": 6,
            "completed": 4,
            "failed": 1,
            "other_terminal": 0,
            "in_progress": 1,
            "waiting": 0,
        },
        "outcomes": [
            {"name": "completed", "count": 4},
            {"name": "failed", "count": 1},
        ],
        "retries": {"chains": 1, "attempts": 2, "kills": 0},
        "providers": [
            {
                "provider": "codex",
                "model": "gpt-5.6",
                "effort": "high",
                "runs": 4,
                "success_rate": 0.75,
                "mean_runtime_seconds": 125.0,
            },
            {
                "provider": "claude",
                "model": "opus",
                "effort": "default",
                "runs": 2,
                "success_rate": 0.5,
                "mean_runtime_seconds": 240.0,
            },
        ],
        "commits": {
            "total_commits": 7,
            "committing_agents": 3,
            "average_per_committing_agent": 7 / 3,
            "distribution": {"zero": 3, "one": 1, "two": 1, "three_plus": 1},
            "top_repos": [{"name": "sase", "count": 7}],
        },
        "questions": {"sessions": 2, "asking_agents": 2},
        "workspaces": [{"project": "sase", "workspace_num": 15, "runs": 6}],
        "buckets": [
            {"start_ts": selected_range.start_ts, "runs": 2},
            {"start_ts": selected_range.start_ts + 86_400, "runs": 4},
        ],
        "runtime_groups": [
            {
                "group": "alpha",
                "runs": 3,
                "total_seconds": 600.0,
                "mean_seconds": 200.0,
                "p50_seconds": 180.0,
                "p95_seconds": 290.0,
                "max_seconds": 300.0,
            }
        ],
    }


def _activity_payload() -> dict:
    return {
        "skills": [{"name": "sase_plan", "count": 8, "distinct_agents": 3}],
        "memories": [{"name": "tui_perf.md", "count": 4, "distinct_agents": 2}],
        "plans": {
            "proposed": 3,
            "tiers": [
                {"name": "epic", "count": 1},
                {"name": "tale", "count": 2},
            ],
            "approved": 2,
            "rejected": 0,
            "pending": 1,
            "phases_per_epic": [{"value": 5, "count": 1}],
            "mean_phases_per_epic": 5.0,
        },
        "questions": {
            "sessions": 2,
            "questions": 3,
            "questions_per_session": [
                {"value": 1, "count": 1},
                {"value": 2, "count": 1},
            ],
            "mean_questions_per_session": 1.5,
        },
    }


def _result(
    view: StatisticsView,
    selected_range: StatsRange,
    group_by: RuntimeGroupBy,
    *,
    empty: bool = False,
) -> StatisticsViewData:
    run_payload = {} if empty else _run_payload(selected_range, group_by)
    activity_payload = {} if empty else _activity_payload()
    return StatisticsViewData(
        view=view,
        selected_range=selected_range,
        runtime_group_by=group_by,
        generated_at=_NOW,
        views=build_statistics_views(run_payload, activity_payload),
    )


def _patch_center(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy]],
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    def load(
        view: StatisticsView,
        selected_range: StatsRange,
        group_by: RuntimeGroupBy,
    ) -> StatisticsViewData:
        calls.append((view, selected_range, group_by))
        return _result(view, selected_range, group_by)

    monkeypatch.setattr(sp, "load_statistics_view", load)


async def _open_statistics(
    page: AcePage,
) -> tuple[ConfigCenterModal, StatisticsPane]:
    modal = ConfigCenterModal(initial_tab="statistics")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _state: bool(modal.query("#statistics")))
    pane = modal.query_one("#statistics", StatisticsPane)
    await page.wait_for(lambda _state: not pane._loading and pane._loaded_once)
    return modal, pane


async def test_statistics_loads_only_after_its_tab_becomes_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: bool(modal.query("#statistics")))
        pane = modal.query_one("#statistics", StatisticsPane)
        await page.pause()

        assert calls == []
        assert pane._worker is None

        await page.press("4")
        await page.wait_for(lambda _state: pane._loaded_once and not pane._loading)

        assert len(calls) == 1
        assert calls[0][0] == "overview"
        assert calls[0][2] == "tribe"


async def test_range_and_group_switches_coalesce_to_latest_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane.action_cycle_range()
        pane.action_cycle_range()
        pane.action_cycle_group()
        await page.wait_for(
            lambda _state: (
                pane._load_debouncer is not None
                and not pane._load_debouncer.is_pending
                and not pane._loading
                and pane._last_result is not None
                and pane._last_result.runtime_group_by == "clan"
            )
        )

        assert len(calls) == 2
        assert calls[-1][1].label == pane._range.label
        assert pane._preset_key == "90d"
        assert pane._runtime_group_by == "clan"


async def test_view_cycle_reuses_composite_result_and_updates_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await page.press("right_square_bracket", "right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "providers")

        assert len(calls) == 1

        await page.press("left_square_bracket")
        await page.wait_for(lambda _state: pane._view == "runs")
        assert len(calls) == 1


async def test_refresh_preserves_selection_and_hidden_tick_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal, pane = await _open_statistics(page)
        pane.action_next_view()
        pane.action_cycle_group()
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        await page.press("r")
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)

        assert calls[-1][0] == "runs"
        assert calls[-1][2] == "clan"
        modal._switch_to("config")
        pane._on_refresh_tick()
        await page.pause()
        assert len(calls) == 3
        assert pane._load_debouncer is not None
        assert not pane._load_debouncer.is_pending


async def test_custom_range_accepts_valid_input_and_rejects_invalid_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await page.press("c")
        custom_input = pane.query_one("#statistics-custom-range", Input)
        assert custom_input.display is True
        custom_input.value = "14d"
        await page.press("enter")
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)

        assert pane._preset_key is None
        assert pane._custom_range_value == "14d"
        assert custom_input.display is False

        accepted_range = pane._range
        await page.press("c")
        custom_input.value = "not-a-range"
        await page.press("enter")
        await page.pause()

        assert pane._range == accepted_range
        assert len(calls) == 2
        assert custom_input.display is True


async def test_configured_bindings_dispatch_and_render_effective_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy]] = []
    _patch_center(monkeypatch, calls)
    registry = load_keymap_registry(
        {
            "keymaps": {
                "statistics": {
                    "prev_view": "f12",
                    "next_view": "f11",
                    "cycle_range": "f10",
                    "custom_range": "f9",
                    "cycle_group": "f8",
                    "refresh": "f7",
                }
            }
        }
    )

    assert statistics_help_bindings(registry.statistics) == [
        ("f12", "Previous View"),
        ("f11", "Next View"),
        ("f10", "Time Range"),
        ("f9", "Custom Range"),
        ("f8", "Group By"),
        ("f7", "Refresh"),
    ]

    async with AcePage() as page:
        page.app._keymap_registry = registry
        _, pane = await _open_statistics(page)

        hints = pane.query_one("#statistics-hints", Static).render().plain
        assert hints == (
            "f12 / f11 views   f10 time range   f9 custom range   "
            "f8 group by   f7 refresh"
        )
        await page.press("f11", "f8")
        await page.wait_for(
            lambda _state: pane._view == "runs" and pane._runtime_group_by == "clan"
        )
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)


async def test_statistics_bindings_are_inactive_on_other_admin_center_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy]] = []
    _patch_center(monkeypatch, calls)
    registry = load_keymap_registry({"keymaps": {"statistics": {"cycle_group": "f12"}}})

    async with AcePage() as page:
        page.app._keymap_registry = registry
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: bool(modal.query("#statistics")))
        pane = modal.query_one("#statistics", StatisticsPane)

        await page.press("f12")
        await page.pause()

        assert pane._runtime_group_by == "tribe"
        assert calls == []


async def test_auto_refresh_soak_keeps_event_loop_and_message_pump_responsive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stall_log = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setenv("SASE_TUI_STALL_PATH", str(stall_log))
    monkeypatch.setenv("SASE_TUI_HITCH_THRESHOLD_SECONDS", "0.5")
    monkeypatch.setenv("SASE_TUI_PUMP_HITCH_THRESHOLD_SECONDS", "0.5")
    monkeypatch.setenv("SASE_TUI_STALL_THRESHOLD_SECONDS", "1.0")
    monkeypatch.setenv("SASE_TUI_PUMP_STALL_THRESHOLD_SECONDS", "1.0")
    monkeypatch.setenv("SASE_TUI_STALL_POLL_INTERVAL", "0.02")
    monkeypatch.setenv("SASE_TUI_PUMP_STALL_POLL_INTERVAL", "0.02")
    monkeypatch.setattr(sp, "_REFRESH_INTERVAL_SECONDS", 0.2)

    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await asyncio.sleep(1.1)
        await page.wait_for(lambda _state: not pane._loading)

        assert len(calls) >= 4
        assert all(call[0] == "overview" for call in calls)

    assert not stall_log.exists() or not stall_log.read_text().strip()


def test_loader_queries_current_activity_and_previous_equal_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, int]] = []
    selected_range = StatsRange(10, 20, "absolute")

    def run_query(**kwargs: int | str) -> dict:
        calls.append(("runs", int(kwargs["start_ts"]), int(kwargs["end_ts"])))
        return _run_payload(selected_range, "tribe")

    def activity_query(**kwargs: int | str) -> dict:
        calls.append(("activity", int(kwargs["start_ts"]), int(kwargs["end_ts"])))
        return _activity_payload()

    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.query_run_stats", run_query
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.query_activity_stats",
        activity_query,
    )

    result = sp.load_statistics_view("overview", selected_range, "tribe")

    assert calls == [
        ("runs", 10, 20),
        ("activity", 10, 20),
        ("runs", 0, 10),
    ]
    assert result.views.overview.agents_run == 6
