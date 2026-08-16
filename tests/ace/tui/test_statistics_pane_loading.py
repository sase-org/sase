"""Loading and refresh coverage for the Statistics pane."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.widgets import Static
from textual.worker import WorkerState

from sase.ace.testing import AcePage
from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_pane_data import StatisticsView
from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.ranges import StatsRange

from tests.ace.tui._statistics_pane_helpers import (
    _activity_payload,
    _assert_range_scope_matches_selection,
    _open_statistics,
    _patch_center,
    _render_plain,
    _result,
    _run_payload,
)
from tests._project_display_case import ProjectDisplayCase


async def test_statistics_loads_only_after_its_tab_becomes_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        await page.pause()

        assert calls == []
        assert not modal.query("#statistics")

        await page.press("5")
        await page.wait_for(lambda _state: bool(modal.query("#statistics")))
        pane = modal.query_one("#statistics", StatisticsPane)
        await page.wait_for(lambda _state: pane._loaded_once and not pane._loading)

        assert len(calls) == 1
        assert calls[0][0] == "overview"
        _assert_range_scope_matches_selection(pane)
        assert pane._range.display_label == "Last 7 days"
        title = pane.query_one("#statistics-title", Static).render().plain
        status = pane.query_one("#statistics-status", Static).render().plain
        assert title == "Statistics · Overview"
        assert pane._range.label not in title
        assert status.startswith("updated ")


def test_stale_project_filter_result_is_discarded_and_rescheduled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._project_filter = "core"
    result = _result(
        pane._view,
        pane._range,
        project_filter="sase",
    )
    worker = SimpleNamespace(result=result, error=None)
    pane._worker = worker  # type: ignore[assignment]
    scheduled: list[bool] = []
    monkeypatch.setattr(pane, "_schedule_load", lambda: scheduled.append(True))

    pane.on_worker_state_changed(
        SimpleNamespace(worker=worker, state=WorkerState.SUCCESS)  # type: ignore[arg-type]
    )

    assert scheduled == [True]
    assert pane._last_result is None


def test_stale_xprompt_focus_result_is_discarded_and_rescheduled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "xprompts"
    pane._xprompt_focus = "split_file"
    result = _result(
        pane._view,
        pane._range,
        xprompt_focus="gh",
    )
    worker = SimpleNamespace(result=result, error=None)
    pane._worker = worker  # type: ignore[assignment]
    scheduled: list[bool] = []
    monkeypatch.setattr(pane, "_schedule_load", lambda: scheduled.append(True))

    pane.on_worker_state_changed(
        SimpleNamespace(worker=worker, state=WorkerState.SUCCESS)  # type: ignore[arg-type]
    )

    assert scheduled == [True]
    assert pane._last_result is None


def test_stale_perf_group_result_is_discarded_and_rescheduled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "perf"
    pane._perf_group_by = "provider"
    result = _result(
        pane._view,
        pane._range,
        perf_group_by="subsystem",
    )
    worker = SimpleNamespace(result=result, error=None)
    pane._worker = worker  # type: ignore[assignment]
    scheduled: list[bool] = []
    monkeypatch.setattr(pane, "_schedule_load", lambda: scheduled.append(True))

    pane.on_worker_state_changed(
        SimpleNamespace(worker=worker, state=WorkerState.SUCCESS)  # type: ignore[arg-type]
    )

    assert scheduled == [True]
    assert pane._last_result is None


async def test_refresh_preserves_selection_and_hidden_tick_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal, pane = await _open_statistics(page)
        pane._set_view("projects")
        pane.action_cycle_group()
        await page.pause()
        await page.press("r")
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)

        assert calls[-1][0] == "projects"
        assert pane._projects_group_by == "patch"
        _assert_range_scope_matches_selection(pane)
        await modal._switch_to("config")
        pane._on_refresh_tick()
        await page.pause()
        assert len(calls) == 2
        assert pane._load_debouncer is not None
        assert not pane._load_debouncer.is_pending


async def test_auto_refresh_soak_keeps_event_loop_and_message_pump_responsive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
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

    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(
        monkeypatch,
        calls,
        project_display_case=project_display_case,
    )

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await asyncio.sleep(1.1)  # sase-test-wait: auto-refresh soak window
        # Soak for a fixed window, then wait on the observed refresh count
        # rather than assuming the window produced it. A loaded CI runner can
        # starve the 0.2s refresh timer enough that 1.1s of wall clock yields
        # only three refreshes, which is scheduling pressure and not the
        # unresponsiveness this test guards against.
        await page.wait_for(lambda _state: len(calls) >= 4, timeout=30.0)
        await page.wait_for(lambda _state: not pane._loading)

        assert len(calls) >= 4
        assert all(call[0] == "overview" for call in calls)
        assert pane._last_result is not None
        rendered = _render_plain(
            pane._overview_renderable(pane._last_result.views.overview)
        )
        assert project_display_case.project_label in rendered
        assert project_display_case.project_key not in rendered

    assert not stall_log.exists() or not stall_log.read_text().strip()


def test_loader_queries_current_activity_and_previous_equal_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, int, str | None, str | None, str | None]] = []
    selected_range = StatsRange(10, 20, "absolute", "Last 10 seconds")
    display_snapshot = ProjectDisplaySnapshot({"sase": "SASE Display"})
    snapshot_loads = 0

    def load_snapshot() -> ProjectDisplaySnapshot:
        nonlocal snapshot_loads
        snapshot_loads += 1
        return display_snapshot

    def run_query(**kwargs: int | str | None) -> dict:
        calls.append(
            (
                "runs",
                int(kwargs["start_ts"]),  # type: ignore[arg-type]
                int(kwargs["end_ts"]),  # type: ignore[arg-type]
                kwargs.get("runtime_group_by"),  # type: ignore[arg-type]
                kwargs.get("project"),  # type: ignore[arg-type]
                kwargs.get("xprompt_focus"),  # type: ignore[arg-type]
            )
        )
        return _run_payload(selected_range, "tribe")

    def activity_query(**kwargs: int | str | None) -> dict:
        calls.append(
            (
                "activity",
                int(kwargs["start_ts"]),  # type: ignore[arg-type]
                int(kwargs["end_ts"]),  # type: ignore[arg-type]
                kwargs.get("runtime_group_by"),  # type: ignore[arg-type]
                kwargs.get("project"),  # type: ignore[arg-type]
                kwargs.get("xprompt_focus"),  # type: ignore[arg-type]
            )
        )
        return _activity_payload()

    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.query_run_stats", run_query
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.query_activity_stats",
        activity_query,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_data.load_project_display_snapshot",
        load_snapshot,
    )
    monkeypatch.setattr("sase.config.core.get_max_running_agents", lambda: 9)

    result = sp.load_statistics_view(
        "overview",
        selected_range,
        "sase",
        "split_file",
    )

    assert calls == [
        ("runs", 10, 20, "tribe", "sase", "split_file"),
        ("activity", 10, 20, None, "sase", None),
        ("runs", 0, 10, "tribe", "sase", None),
    ]
    assert result.views.overview.agents_run == 6
    assert result.project_filter == "sase"
    assert result.xprompt_focus == "split_file"
    assert snapshot_loads == 1
    assert result.project_display_snapshot is display_snapshot
    assert result.views.projects.projects[0].project_label == "SASE Display"
    # The current global runner limit is captured off-thread and carried on the
    # immutable result so rendering performs no configuration I/O.
    assert result.views.runners.current_limit == 9
