"""Tests for the TUI's authoritative machine-capacity report feed."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from sase.ace.tui.actions.event_refresh._auto_refresh import (
    _CapacityReportFeedMixin,
)
from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    prepare_loaded_agents_apply_boundary,
)
from sase.ace.tui.actions.agents._loading_filter import AgentLoadingFilterMixin
from sase.ace.tui.models._agent_runner_slot_types import RunnerCapacitySnapshot
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks
from sase.config.runner_limit_override import EffectiveRunnerLimitSnapshot
from sase.core.runner_slots import MachineCapacityReport, MachineCapacityRecordInputs

from ._agent_runner_slots_helpers import _agent


def _report(
    *,
    occupied: float = 5.0,
    claims: tuple[dict[str, object], ...] | None = None,
    waiters: tuple[dict[str, object], ...] = (),
) -> MachineCapacityReport:
    now = time.time()
    report_claims = claims or (
        {
            "owner_key": "claim-worker",
            "owner_artifact_dir": "/tmp/project/artifacts/worker",
            "artifact_dirs": ["/tmp/project/artifacts/worker"],
            "occupied_capacity": 1.0,
        },
    )
    accounting = (
        {
            "artifact_dir": "/tmp/project/artifacts/verify",
            "agent_name": "verify-monitor",
            "state": "holding",
            "charged_weight": 1.0,
            "claim_owner_key": "claim-verify",
        },
        {
            "artifact_dir": "/tmp/project/artifacts/wait-zero",
            "agent_name": "wait-monitor",
            "state": "holding",
            "charged_weight": 0.0,
            "claim_owner_key": "claim-zero",
        },
    )
    raw = {
        "occupied_capacity": occupied,
        "occupied_lanes": 6,
        "effective_limit": 8.0,
        "claims": list(report_claims),
        "waiters": list(waiters),
        "accounting": list(accounting),
        "accounting_valid": True,
    }
    return MachineCapacityReport(
        machine="athena",
        computed_at=now,
        scanned_at=now,
        token="capacity-token-1",
        scan_current=True,
        effective_limit=8.0,
        limit=EffectiveRunnerLimitSnapshot(
            configured_limit=8,
            temporary_override=None,
            captured_at=now,
        ),
        occupied_capacity=occupied,
        occupied_lanes=6,
        over_limit=False,
        claims=tuple(report_claims),
        waiters=waiters,
        accounting=accounting,
        diagnostics=(),
        accounting_valid=True,
        accounting_available=True,
        raw_snapshot=raw,
        record_inputs=(
            MachineCapacityRecordInputs(
                artifact_dir="/tmp/project/artifacts/verify",
                turn_kind="monitor",
                turn_role="monitor",
                monitor_id="verify-1",
                slot_requested_at=None,
                authored_queue_capacity=None,
                run_started_at=None,
            ),
        ),
    )


def test_authoritative_report_drives_header_and_waiter_context_without_roster() -> None:
    waiter = _agent(
        "filtered-waiter",
        slot_requested_at="2026-10-27T10:00:00Z",
        artifacts_dir="/tmp/project/artifacts/waiter",
    )
    raw = _report(
        waiters=(
            {
                "artifact_dir": waiter.artifacts_dir,
                "queue_position": 3,
                "slot_requested_at": "2026-10-27T10:00:00Z",
                "requested_weight": 1.0,
                "priority": 0,
                "eligible": False,
                "admission_limit": 4.0,
                "blockers": [{"code": "insufficient-capacity"}],
            },
        )
    )

    capacity = refresh_runner_slot_context(
        [waiter],
        raw_snapshot=raw.raw_snapshot,
        report=raw,
    )
    filtered = refresh_runner_slot_context(
        [],
        raw_snapshot=raw.raw_snapshot,
        report=raw,
    )

    assert capacity.source == "authoritative"
    assert capacity.occupied_capacity == 5.0
    assert capacity.slots_in_use == 6
    assert capacity.occupied_capacity == filtered.occupied_capacity
    assert capacity.holders[0].label == "verify-monitor"
    assert any(
        holder.label == "wait-monitor" and holder.weight == 0
        for holder in capacity.holders
    )
    assert waiter.status == "QUEUED"
    assert waiter.runner_slot_queue_position == 3
    assert waiter.runner_capacity_blockers == ({"code": "insufficient-capacity"},)


def test_each_roster_apply_uses_the_latest_report_and_keeps_an_estimate_witness() -> (
    None
):
    waiter = _agent(
        "filtered-waiter",
        slot_requested_at="2026-10-27T10:00:00Z",
        artifacts_dir="/tmp/project/artifacts/waiter",
    )
    report = _report(
        waiters=(
            {
                "artifact_dir": waiter.artifacts_dir,
                "queue_position": 2,
                "slot_requested_at": "2026-10-27T10:00:00Z",
                "requested_weight": 1.0,
                "priority": 0,
                "eligible": False,
                "admission_limit": 4.0,
                "blockers": [{"code": "insufficient-capacity"}],
            },
        )
    )
    prep = PreparedApplyData(
        filtered_agents=[waiter],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[waiter],
        dismissed_agent_objects=[],
        capacity_agents=[waiter],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=[],
        dismissed_agents=set(),
        agents_seen_complete_history=False,
        hide_non_run_agents=False,
        load_state=None,
        fold_levels={},
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
        capacity_report=report,
    )

    boundary = prepare_loaded_agents_apply_boundary(
        prep,
        snapshot,
        merge_incomplete=False,
        effective_runner_limit=8,
        graphs_owned=True,
    )

    assert boundary.runner_capacity.source == "authoritative"
    assert boundary.runner_capacity.occupied_capacity == 5.0
    assert boundary.runner_capacity_estimate.source == "estimate"
    assert boundary.prep.filtered_agents[0].status == "QUEUED"
    assert boundary.prep.filtered_agents[0].runner_slot_queue_position == 2


def test_report_refresh_copies_queue_context_to_live_rows_and_patches_them() -> None:
    live = _agent("waiter", status="WAITING")
    updated = _agent(
        "waiter",
        status="QUEUED",
        runner_slots_in_use=6,
        runner_occupied_capacity=5.0,
        runner_effective_limit=8.0,
        runner_slot_queue_position=2,
        runner_slot_queue_size=1,
        runner_capacity_blockers=({"code": "insufficient-capacity"},),
    )

    class _App:
        current_tab = "agents"
        _agents = [live]
        _agents_with_children = [live]
        _agents_capacity_with_children = [live]
        _agents_query_result = [live]
        patched: list[object] = []

        def _try_patch_agent_row(self, row: object, *, refresh_info: bool) -> bool:
            del refresh_info
            self.patched.append(row)
            return True

    app = _App()
    AgentLoadingFilterMixin._apply_agents_capacity_row_updates(app, [updated])

    assert live.status == "QUEUED"
    assert live.runner_slot_queue_position == 2
    assert live.runner_capacity_blockers == ({"code": "insufficient-capacity"},)
    assert app.patched == [live]


class _FeedApp(_CapacityReportFeedMixin):
    def __init__(self, report_source: object) -> None:
        self._machine_capacity_report_source = report_source
        self._capacity_reports_installed: asyncio.Queue[MachineCapacityReport] = (
            asyncio.Queue()
        )
        self._machine_capacity_token_probe = lambda: "token"
        self.current_tab = "agents"
        self._agents_first_load_done = False
        self._machine_capacity_refresh_generation = 0
        self._machine_capacity_refresh_scheduled = False
        self._machine_capacity_refresh_running = False
        self._machine_capacity_refresh_pending = False
        self._machine_capacity_report_generation = 0
        self._machine_capacity_report_mono = 0.0
        self._machine_capacity_feed_tasks: set[asyncio.Task[object]] = set()
        self._capacity_telemetry_tasks: set[asyncio.Task[object]] = set()
        self._telemetry_records: list[dict[str, object]] = []
        self._schedule_capacity_telemetry_write = self._telemetry_records.append

    def _update_agents_info_panel(self) -> None:
        pass

    def _bump_agents_capacity_generation(self) -> int:
        return 1

    def _install_machine_capacity_report(self, report: MachineCapacityReport) -> None:
        super()._install_machine_capacity_report(report)
        self._capacity_reports_installed.put_nowait(report)


@pytest.mark.asyncio
async def test_feed_moves_from_roster_estimate_to_authoritative_report() -> None:
    app = _FeedApp(lambda: _report())
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
        return _report(occupied=float(4 + calls))

    app = _FeedApp(source)
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
        return _report()

    app = _FeedApp(source)
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

    app = _FeedApp(lambda: _report())
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
        return _report()

    app = _FeedApp(source)
    app._machine_capacity_token_probe = probe  # type: ignore[assignment]
    app._machine_capacity_observed_token = "token"
    app._install_machine_capacity_report(_report())
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
        return _report()

    app = _FeedApp(source)
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
    app = _FeedApp(lambda: _report(occupied=5.0))
    app._agent_runner_capacity_estimate = RunnerCapacitySnapshot(
        effective_limit=8,
        occupied_capacity=2,
        claim_artifact_dirs=("/tmp/roster/worker",),
    )
    app._agents_capacity_estimate_generation = 1

    app._install_machine_capacity_report(_report(occupied=5.0))
    assert not any(
        record["event"] == "capacity_drift" for record in app._telemetry_records
    )
    app._install_machine_capacity_report(_report(occupied=5.0))

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
