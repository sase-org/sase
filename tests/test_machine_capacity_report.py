"""Authoritative machine capacity report: scan reuse, liveness, and provenance."""

from __future__ import annotations

import json
import threading

import pytest

from sase.config.runner_limit_override import (
    EffectiveRunnerLimitSnapshot,
    TemporaryRunnerLimitOverride,
)
from sase.core.agent_hold_facade import peek_active_agent_holds
from sase.core.agent_hold_store import agent_hold_store_path
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.runner_slots import (
    DISPLAY_RESCAN_INTERVAL_SECONDS,
    load_or_refresh_runner_slot_scan,
    machine_capacity_report,
    machine_capacity_report_from_records,
    runner_capacity_snapshot,
    runner_slot_state_token,
)
from sase.core.runner_slots import _machine_capacity as _machine_capacity_mod
from tests._runner_slots_helpers import _always_live, _record


@pytest.fixture(autouse=True)
def _isolate_machine_capacity_report(monkeypatch: pytest.MonkeyPatch) -> None:
    _machine_capacity_mod._last_display_rescan_at = None
    monkeypatch.setattr(
        "sase.config.core.get_configured_max_running_agents", lambda: 10
    )
    monkeypatch.setattr(
        "sase.config.runner_limit_override.get_active_runner_limit_override",
        lambda now=None: _ace_override(),
    )
    monkeypatch.setattr(
        "sase.config.core.get_runner_slot_deference_seconds_per_step",
        lambda: 0,
    )
    monkeypatch.setattr(
        "sase.config.core.get_runner_slot_deference_max_seconds",
        lambda: 0,
    )
    monkeypatch.setattr(
        "sase.core.agent_hold_facade.peek_active_agent_holds",
        lambda **_: [],
    )
    monkeypatch.setattr(
        "sase.core.runner_slots._machine_capacity.local_machine_label",
        lambda: "athena",
    )


def _ace_override() -> TemporaryRunnerLimitOverride:
    return TemporaryRunnerLimitOverride(
        version=1,
        limit=8,
        created_at=1_000.0,
        expires_at=None,
        source="ace",
    )


def _limit(
    now: float,
    *,
    configured: int = 10,
    override: int | None = 8,
) -> EffectiveRunnerLimitSnapshot:
    return EffectiveRunnerLimitSnapshot(
        configured_limit=configured,
        temporary_override=None
        if override is None
        else _ace_override()
        if override == 8
        else TemporaryRunnerLimitOverride(
            version=1,
            limit=override,
            created_at=now - 1.0,
            expires_at=None,
            source="ace",
        ),
        captured_at=now,
    )


def _screenshot_records() -> list[AgentArtifactRecordWire]:
    return [
        _record("/worker-a", run_started=True),
        _record("/worker-b", run_started=True),
        _record("/worker-c", run_started=True),
        _record(
            "/verify-a",
            agent_session="verify-a",
            agent_session_role="monitor",
            monitor_id="verify-a-turn",
            queue_weight=1.0,
        ),
        _record(
            "/verify-b",
            agent_session="verify-b",
            agent_session_role="monitor",
            monitor_id="verify-b-turn",
            queue_weight=1.0,
        ),
        _record(
            "/cutover",
            agent_session="cutover",
            agent_session_role="monitor",
            monitor_id="cutover-turn",
            queue_weight=0.0,
            queue_weight_explicit=True,
        ),
    ]


def _report_from_records(
    records: list[AgentArtifactRecordWire],
    *,
    now: float = 2_000.0,
    is_live=_always_live,
    configured: int = 10,
    override: int | None = 8,
    scan_current: bool = True,
    token: str = "tok",
):
    return machine_capacity_report_from_records(
        records,
        is_live,
        now=now,
        token=token,
        scanned_at=now,
        scan_current=scan_current,
        limit=_limit(now, configured=configured, override=override),
    )


def test_screenshot_shape_report_is_five_of_eight_with_override_provenance() -> None:
    report = _report_from_records(_screenshot_records())

    assert report.machine == "athena"
    assert report.occupied_capacity == 5.0
    assert report.effective_limit == 8.0
    assert report.over_limit is False
    assert report.accounting_valid is True
    assert report.accounting_available is True
    assert len(report.accounting) == 6
    assert report.limit.configured_limit == 10
    assert report.limit.temporary_override is not None
    assert report.limit.temporary_override.limit == 8
    assert report.limit.temporary_override.source == "ace"
    assert report.limit.temporary_override.expires_at is None

    inputs = {item.artifact_dir: item for item in report.record_inputs}
    assert inputs["/verify-a"].turn_kind == "monitor"
    assert inputs["/verify-a"].turn_role == "monitor"
    assert inputs["/verify-a"].monitor_id == "verify-a-turn"
    assert inputs["/worker-a"].run_started_at is not None
    assert inputs["/cutover"].monitor_id == "cutover-turn"


def test_token_change_inside_rate_limit_window_serves_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = ["a"]
    monkeypatch.setattr(
        "sase.core.runner_slots._machine_capacity.runner_slot_state_token",
        lambda: tokens[0],
    )
    calls: list[str] = []

    def collect() -> list[AgentArtifactRecordWire]:
        calls.append(tokens[0])
        if tokens[0] == "a":
            return _screenshot_records()
        return [*_screenshot_records(), _record("/worker-d", run_started=True)]

    first = machine_capacity_report(now=1_000.0, collect=collect, is_live=_always_live)
    tokens[0] = "b"
    second = machine_capacity_report(
        now=1_000.0 + DISPLAY_RESCAN_INTERVAL_SECONDS - 1.0,
        collect=collect,
        is_live=_always_live,
    )

    assert first.scan_current is True
    assert first.occupied_capacity == 5.0
    assert second.scan_current is False
    assert second.occupied_capacity == 5.0
    assert second.token == "a"
    assert calls == ["a"]


def test_force_rescan_ignores_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    tokens = ["a"]
    monkeypatch.setattr(
        "sase.core.runner_slots._machine_capacity.runner_slot_state_token",
        lambda: tokens[0],
    )
    calls: list[str] = []

    def collect() -> list[AgentArtifactRecordWire]:
        calls.append(tokens[0])
        if tokens[0] == "a":
            return _screenshot_records()
        return [*_screenshot_records(), _record("/worker-d", run_started=True)]

    machine_capacity_report(now=1_000.0, collect=collect, is_live=_always_live)
    tokens[0] = "b"
    forced = machine_capacity_report(
        now=1_001.0,
        collect=collect,
        is_live=_always_live,
        force_rescan=True,
    )

    assert forced.scan_current is True
    assert forced.occupied_capacity == 6.0
    assert calls == ["a", "b"]


def test_dead_pid_drops_out_without_a_rescan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _screenshot_records()
    monkeypatch.setattr(
        "sase.core.runner_slots._machine_capacity.runner_slot_state_token",
        lambda: "seed",
    )
    load_or_refresh_runner_slot_scan(
        lambda: records, max_age=0.0, now=1_000.0, token="seed"
    )
    calls: list[int] = []

    def collect() -> list[AgentArtifactRecordWire]:
        calls.append(1)
        return records

    def is_live(record: AgentArtifactRecordWire) -> bool:
        return record.artifact_dir != "/worker-a"

    report = machine_capacity_report(now=1_500.0, collect=collect, is_live=is_live)

    assert calls == []
    assert report.scan_current is True
    assert report.occupied_capacity == 4.0


def test_older_core_snapshot_without_accounting_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = runner_capacity_snapshot

    def stripped(
        records: list[AgentArtifactRecordWire],
        is_live,
        **kwargs: object,
    ):
        snapshot = dict(real(records, is_live, **kwargs))
        snapshot.pop("accounting", None)
        snapshot.pop("accounting_valid", None)
        return snapshot

    monkeypatch.setattr(
        "sase.core.runner_slots._admission_snapshot.runner_capacity_snapshot",
        stripped,
    )
    report = _report_from_records(_screenshot_records())
    assert report.accounting_available is False
    assert report.accounting_valid is False
    assert report.accounting == ()
    assert report.occupied_capacity == 5.0


def test_invalid_weight_is_not_free_capacity() -> None:
    bad = _record("/bad", run_started=True)
    assert bad.agent_meta is not None
    object.__setattr__(bad.agent_meta, "queue_weight_invalid", True)
    report = _report_from_records([*_screenshot_records(), bad])

    assert report.accounting_valid is False
    assert report.occupied_capacity == 5.0
    assert report.over_limit is False


def test_over_limit_flag_when_occupied_exceeds_limit() -> None:
    report = _report_from_records(_screenshot_records(), configured=1, override=None)
    assert report.effective_limit == 1.0
    assert report.occupied_capacity == 5.0
    assert report.over_limit is True


def test_report_never_takes_admission_lock_or_bumps_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.runner_slots._machine_capacity.runner_slot_state_token",
        lambda: "seed",
    )
    load_or_refresh_runner_slot_scan(
        _screenshot_records, max_age=0.0, now=1_000.0, token="seed"
    )
    before = runner_slot_state_token()

    def flock(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("capacity report must not take runner_slots.lock")

    def notify() -> None:
        raise AssertionError("capacity report must not bump runner_slots.token")

    monkeypatch.setattr("sase.core.runner_slots._admission_lock.fcntl.flock", flock)
    monkeypatch.setattr(
        "sase.core.runner_slots._signal.notify_runner_slot_state_changed",
        notify,
    )
    report = machine_capacity_report(
        now=1_001.0, collect=_screenshot_records, is_live=_always_live
    )

    assert report.occupied_capacity == 5.0
    assert runner_slot_state_token() == before


def test_in_flight_display_rescan_serves_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.core.runner_slots._machine_capacity.runner_slot_state_token",
        lambda: "fresh",
    )
    load_or_refresh_runner_slot_scan(
        lambda: _screenshot_records(),
        max_age=0.0,
        now=1_000.0,
        token="stale",
    )
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def collect() -> list[AgentArtifactRecordWire]:
        calls.append(1)
        started.set()
        assert release.wait(timeout=2.0)
        return [*_screenshot_records(), _record("/worker-d", run_started=True)]

    results: list[object] = []

    def worker() -> None:
        results.append(
            machine_capacity_report(now=2_000.0, collect=collect, is_live=_always_live)
        )

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(timeout=2.0)
    stale = machine_capacity_report(now=2_000.1, collect=collect, is_live=_always_live)
    release.set()
    thread.join(timeout=2.0)

    assert stale.scan_current is False
    assert stale.occupied_capacity == 5.0
    assert results
    finished = results[0]
    assert finished.scan_current is True
    assert finished.occupied_capacity == 6.0
    assert calls == [1]


def test_waiter_display_inputs_carry_authored_budget() -> None:
    waiter = _record(
        "/waiter",
        requested_at="2026-07-12T12:01:00Z",
        wait_runners=2,
        wait_priority=10,
        queue_weight=1.0,
        queue_weight_explicit=True,
    )
    report = _report_from_records([waiter], configured=8, override=None)
    (inputs,) = report.record_inputs
    assert inputs.slot_requested_at == "2026-07-12T12:01:00Z"
    assert inputs.authored_queue_capacity == 2


def _hold_record(key: str, expires_at: float) -> dict[str, object]:
    return {
        "schema_version": 3,
        "armer": {
            "kind": "cli",
            "key": key,
            "display": key,
            "project": "proj",
        },
        "scope": {"kind": "host"},
        "selectors": {},
        "created_at": 1.0,
        "expires_at": expires_at,
    }


def test_tui_local_machine_label_is_the_core_function() -> None:
    from sase.ace.tui.modals.machines_pane_rendering import (
        local_machine_label as tui_label,
    )
    from sase.core.local_machine import local_machine_label as core_label

    assert tui_label is core_label


def test_peek_active_holds_omits_expired_without_writing() -> None:
    path = agent_hold_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 3,
        "holds": {
            "cli:live": _hold_record("cli:live", 9_000.0),
            "cli:expired": _hold_record("cli:expired", 10.0),
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()

    holds = peek_active_agent_holds(now=100.0)

    assert [hold["armer"]["key"] for hold in holds] == ["cli:live"]
    assert path.read_bytes() == before
