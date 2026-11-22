"""Feed lifecycle tests for the machine-capacity report feed."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from sase.ace.tui.models._agent_runner_slot_types import RunnerCapacitySnapshot
from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks
from sase.core.runner_slots import MachineCapacityReport
from tests.ace.tui._machine_capacity_report_feed_helpers import FeedApp, make_report


@pytest.mark.asyncio
async def test_feed_moves_from_roster_estimate_to_authoritative_report() -> None:
    app = FeedApp(lambda: make_report())
    estimate = RunnerCapacitySnapshot(
        effective_limit=8,
        occupied_capacity=3,
        source="estimate",
    )
    app._agent_runner_capacity_estimate = estimate
    app._agent_runner_capacity = estimate

    app._request_machine_capacity_report_refresh(source="test")
    await asyncio.wait_for(app._capacity_reports_installed.get(), timeout=1)

    assert app._machine_capacity_report is not None
    assert app._agent_runner_capacity.source == "authoritative"
    assert app._agent_runner_capacity.occupied_capacity == 5.0
    assert any(record["event"] == "capacity_gauge" for record in app._telemetry_records)


@pytest.mark.asyncio
async def test_token_change_during_compute_coalesces_to_one_trailing_report() -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def source() -> MachineCapacityReport:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            release.wait(timeout=2)
        return make_report(occupied=float(4 + calls))

    app = FeedApp(source)
    app._request_machine_capacity_report_refresh(source="initial")
    assert await asyncio.to_thread(entered.wait, 1)
    app._request_machine_capacity_report_refresh(source="token_change")
    release.set()
    await asyncio.wait_for(app._capacity_reports_installed.get(), timeout=1)

    assert calls == 2
    assert app._machine_capacity_report.occupied_capacity == 6.0
    assert app._machine_capacity_report_generation == 1


@pytest.mark.asyncio
async def test_feed_tasks_cancel_at_teardown() -> None:
    entered = threading.Event()
    release = threading.Event()

    def source() -> MachineCapacityReport:
        entered.set()
        release.wait(timeout=2)
        return make_report()

    app = FeedApp(source)
    app._request_machine_capacity_report_refresh(source="test")
    assert await asyncio.to_thread(entered.wait, 1)
    task = next(iter(app._machine_capacity_feed_tasks))

    class _Timer:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    timer = _Timer()
    app._machine_capacity_feed_timer = timer
    app._stop_machine_capacity_report_feed()
    cancel_pump_free_tasks(app)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert timer.stopped


def test_feed_tick_stats_nothing_on_the_ui_thread() -> None:
    probes: list[int] = []

    def probe() -> str:
        probes.append(1)
        return "token"

    app = FeedApp(lambda: make_report())
    app._machine_capacity_token_probe = probe  # type: ignore[assignment]
    app._on_machine_capacity_feed_tick()

    assert probes == []
    assert app._machine_capacity_refresh_scheduled is False


@pytest.mark.asyncio
async def test_refresh_task_skips_build_when_token_unchanged() -> None:
    builds: list[int] = []
    probes: list[int] = []

    def probe() -> str:
        probes.append(1)
        return "token"

    def source() -> MachineCapacityReport:
        builds.append(1)
        return make_report()

    app = FeedApp(source)
    app._machine_capacity_token_probe = probe  # type: ignore[assignment]
    app._machine_capacity_observed_token = "token"
    app._install_machine_capacity_report(make_report())
    assert app._capacity_reports_installed.get_nowait() is not None

    generation = int(app._machine_capacity_refresh_generation) + 1
    app._machine_capacity_refresh_generation = generation
    await app._run_machine_capacity_report_refresh(generation=generation)

    assert probes == [1]
    assert builds == []
    assert app._capacity_reports_installed.empty()
    assert app._machine_capacity_refresh_running is False


@pytest.mark.asyncio
async def test_refresh_task_rebuilds_when_token_changes() -> None:
    builds: list[int] = []

    def source() -> MachineCapacityReport:
        builds.append(1)
        return make_report()

    app = FeedApp(source)
    app._machine_capacity_token_probe = lambda: "new-token"  # type: ignore[assignment]
    app._machine_capacity_observed_token = "old-token"
    app._machine_capacity_report_mono = time.monotonic()

    generation = int(app._machine_capacity_refresh_generation) + 1
    app._machine_capacity_refresh_generation = generation
    await app._run_machine_capacity_report_refresh(generation=generation)

    assert builds == [1]
    assert app._machine_capacity_observed_token == "new-token"
    assert app._capacity_reports_installed.get_nowait() is not None


def test_drift_telemetry_waits_for_two_distinct_comparisons() -> None:
    app = FeedApp(lambda: make_report(occupied=5.0))
    app._agent_runner_capacity_estimate = RunnerCapacitySnapshot(
        effective_limit=8,
        occupied_capacity=2,
        claim_artifact_dirs=("/tmp/roster/worker",),
    )
    app._agents_capacity_estimate_generation = 1

    app._install_machine_capacity_report(make_report(occupied=5.0))
    assert not any(
        record["event"] == "capacity_drift" for record in app._telemetry_records
    )
    app._install_machine_capacity_report(make_report(occupied=5.0))

    drift = [
        record
        for record in app._telemetry_records
        if record["event"] == "capacity_drift"
    ]
    assert len(drift) == 1
    assert drift[0]["roster_occupied"] == 2.0
    assert drift[0]["report_occupied"] == 5.0
    assert drift[0]["differing_artifact_dirs"] == [
        "/tmp/project/artifacts/worker",
        "/tmp/roster/worker",
    ]
