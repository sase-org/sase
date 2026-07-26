"""Integration tests for side-effect-free AXE status collection."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import sase.axe.status_collector as collector
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.desired_state import AxeDesiredState
from sase.axe.state import LumberjackStatus
from sase.axe._process_types import AxeOrchestratorProbe


NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


def _config(
    *,
    lumberjacks: dict[str, LumberjackConfig] | None = None,
) -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3,
        max_agent_runners=4,
        lumberjacks=lumberjacks or {},
    )


def _lumberjack_config(
    name: str = "hooks",
    *,
    interval: int = 20,
    chops: list[ChopConfig] | None = None,
) -> LumberjackConfig:
    return LumberjackConfig(
        name=name,
        description=f"Collect {name} test status",
        interval=interval,
        chops=chops or [ChopConfig(name="hook_checks", description="test")],
    )


def _status(
    name: str = "hooks",
    *,
    pid: int = 200,
    started_at: str = "2026-07-23T11:00:00+00:00",
    heartbeat: str | None = "2026-07-23T11:59:00+00:00",
    errors: int = 0,
    state: str = "running",
) -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=pid,
        started_at=started_at,
        status=state,  # type: ignore[arg-type]
        interval=20,
        chops=["hook_checks"],
        last_cycle=heartbeat,
        cycles_run=5,
        errors_encountered=errors,
        uptime_seconds=3600,
    )


def _probe(
    *,
    lock_held: bool = True,
    lock_pid: int | None = 100,
    orchestrator_pid: int | None = 100,
    legacy_pid: int | None = None,
) -> AxeOrchestratorProbe:
    return AxeOrchestratorProbe(
        lock_held=lock_held,
        lock_holder_pid=lock_pid,
        orchestrator_pid_file_pid=orchestrator_pid,
        legacy_pid=legacy_pid,
        running_pid=lock_pid or orchestrator_pid or legacy_pid,
    )


def _patch_host(
    monkeypatch,
    *,
    config: AxeConfig | None = None,
    probe: AxeOrchestratorProbe | None = None,
    live_pids: set[int] | None = None,
) -> list[bool]:
    cleanup_calls: list[bool] = []
    effective_config = config or _config()
    effective_probe = probe or _probe()
    effective_live_pids = live_pids if live_pids is not None else {100}

    monkeypatch.setattr(collector, "load_axe_config", lambda: effective_config)

    def fake_probe(*, cleanup: bool = True) -> AxeOrchestratorProbe:
        cleanup_calls.append(cleanup)
        return effective_probe

    monkeypatch.setattr(collector, "probe_orchestrator", fake_probe)
    monkeypatch.setattr(
        collector,
        "is_process_running",
        lambda pid: pid in effective_live_pids,
    )
    monkeypatch.setattr(collector, "count_hook_runners_global", lambda: 1)
    monkeypatch.setattr(collector, "count_agent_runners_global", lambda: 2)
    monkeypatch.setattr(collector, "read_desired_state", lambda: None)
    monkeypatch.setattr(collector, "read_maintenance", lambda: None)
    monkeypatch.setattr(collector, "read_recent_lifecycle_events", lambda *, limit: [])
    monkeypatch.setattr(collector, "list_lumberjack_names", lambda: [])
    monkeypatch.setattr(collector, "read_lumberjack_status", lambda _name: None)
    monkeypatch.setattr(collector, "read_lumberjack_pid", lambda _name: None)
    return cleanup_calls


@pytest.mark.parametrize(
    ("probe", "live_pids", "orchestrator_state", "snapshot_state"),
    [
        (_probe(), {100}, "running", "running"),
        (
            _probe(lock_pid=100, orchestrator_pid=101),
            {100, 101},
            "incoherent",
            "degraded",
        ),
        (_probe(lock_pid=100, orchestrator_pid=100), set(), "incoherent", "degraded"),
        (
            _probe(lock_held=False, lock_pid=None, orchestrator_pid=100),
            {100},
            "incoherent",
            "degraded",
        ),
        (
            _probe(
                lock_held=False,
                lock_pid=None,
                orchestrator_pid=None,
                legacy_pid=None,
            ),
            set(),
            "stopped",
            "not_started",
        ),
    ],
)
def test_collector_preserves_every_lock_pid_coherence_shape(
    monkeypatch,
    probe: AxeOrchestratorProbe,
    live_pids: set[int],
    orchestrator_state: str,
    snapshot_state: str,
) -> None:
    cleanup_calls = _patch_host(
        monkeypatch,
        probe=probe,
        live_pids=live_pids,
    )

    snapshot = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert snapshot.orchestrator.state == orchestrator_state
    assert snapshot.state == snapshot_state
    assert cleanup_calls == [False]


@pytest.mark.parametrize(
    ("heartbeat", "expected_state", "expected_health"),
    [
        ("2026-07-23T11:59:00+00:00", "running", "healthy"),
        ("2026-07-23T11:58:59+00:00", "stale_heartbeat", "unhealthy"),
    ],
)
def test_heartbeat_is_healthy_at_threshold_and_stale_one_second_later(
    monkeypatch,
    heartbeat: str,
    expected_state: str,
    expected_health: str,
) -> None:
    config = _config(lumberjacks={"hooks": _lumberjack_config()})
    _patch_host(monkeypatch, config=config, live_pids={100, 200})
    monkeypatch.setattr(
        collector,
        "read_lumberjack_status",
        lambda _name: _status(heartbeat=heartbeat, errors=7),
    )

    snapshot = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert snapshot.lumberjacks[0].heartbeat_age_seconds in {60, 61}
    assert snapshot.lumberjacks[0].state == expected_state
    assert snapshot.health == expected_health
    if expected_health == "healthy":
        assert snapshot.lumberjacks[0].errors_encountered == 7


@pytest.mark.parametrize(
    ("status", "live_pids", "expected_state"),
    [
        (None, {100}, "not_reporting"),
        (_status(), {100}, "stale_process"),
        (_status(state="error"), {100, 200}, "error"),
        (_status(state="stopped"), {100, 200}, "error"),
    ],
)
def test_configured_lumberjack_failure_shapes(
    monkeypatch,
    status: LumberjackStatus | None,
    live_pids: set[int],
    expected_state: str,
) -> None:
    config = _config(lumberjacks={"hooks": _lumberjack_config()})
    _patch_host(monkeypatch, config=config, live_pids=live_pids)
    monkeypatch.setattr(
        collector,
        "read_lumberjack_status",
        lambda _name: status,
    )

    snapshot = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert snapshot.lumberjacks[0].state == expected_state
    assert snapshot.health == "unhealthy"


@pytest.mark.parametrize(
    ("started_at", "expected_state"),
    [
        ("2026-07-23T11:59:00+00:00", "running"),
        ("2026-07-23T11:58:59+00:00", "stale_heartbeat"),
    ],
)
def test_missing_heartbeat_uses_start_age_threshold(
    monkeypatch,
    started_at: str,
    expected_state: str,
) -> None:
    config = _config(lumberjacks={"hooks": _lumberjack_config()})
    _patch_host(monkeypatch, config=config, live_pids={100, 200})
    monkeypatch.setattr(
        collector,
        "read_lumberjack_status",
        lambda _name: _status(started_at=started_at, heartbeat=None),
    )

    snapshot = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert snapshot.lumberjacks[0].state == expected_state


def test_intentional_stop_and_fresh_state_remain_healthy(monkeypatch) -> None:
    probe = _probe(
        lock_held=False,
        lock_pid=None,
        orchestrator_pid=None,
        legacy_pid=None,
    )
    config = _config(lumberjacks={"hooks": _lumberjack_config()})
    _patch_host(monkeypatch, config=config, probe=probe, live_pids=set())
    monkeypatch.setattr(
        collector,
        "read_desired_state",
        lambda: AxeDesiredState(
            state="stopped",
            source="test",
            timestamp="2026-07-23T11:00:00+00:00",
        ),
    )

    stopped = collector.collect_axe_status_snapshot(clock=lambda: NOW)
    monkeypatch.setattr(collector, "read_desired_state", lambda: None)
    fresh = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert (stopped.state, stopped.health, stopped.issues) == (
        "stopped",
        "healthy",
        (),
    )
    assert (fresh.state, fresh.health, fresh.issues) == (
        "not_started",
        "healthy",
        (),
    )


def test_desired_running_down_and_active_maintenance(monkeypatch) -> None:
    stopped_probe = _probe(
        lock_held=False,
        lock_pid=None,
        orchestrator_pid=None,
        legacy_pid=None,
    )
    _patch_host(monkeypatch, probe=stopped_probe, live_pids=set())
    monkeypatch.setattr(
        collector,
        "read_desired_state",
        lambda: AxeDesiredState(
            state="running",
            source="test",
            timestamp="2026-07-23T11:00:00+00:00",
        ),
    )

    down = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert (down.state, down.health, down.exit_code) == ("down", "unhealthy", 1)

    _patch_host(monkeypatch, live_pids={100})
    monkeypatch.setattr(
        collector,
        "read_maintenance",
        lambda: {
            "reason": "upgrade",
            "pid": 999,
            "started_at": "2026-07-23T11:59:30+00:00",
        },
    )
    maintenance = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert maintenance.state == "maintenance"
    assert maintenance.health == "healthy"
    assert maintenance.maintenance is not None
    assert maintenance.maintenance.age_seconds == 30


def test_lumberjack_union_is_sorted_deduplicated_and_filters_dead_orphans(
    monkeypatch,
) -> None:
    config = _config(
        lumberjacks={
            "zeta": _lumberjack_config(
                "zeta",
                chops=[
                    ChopConfig(name="beta", description="test"),
                    ChopConfig(name="alpha", description="test"),
                    ChopConfig(name="alpha", description="test"),
                ],
            )
        }
    )
    _patch_host(monkeypatch, config=config, live_pids={100, 200, 300})
    monkeypatch.setattr(
        collector,
        "list_lumberjack_names",
        lambda: ["vanished", "orphan", "dead", "zeta"],
    )
    monkeypatch.setattr(
        collector,
        "read_lumberjack_status",
        lambda name: _status(name=name, pid=200) if name == "zeta" else None,
    )
    monkeypatch.setattr(
        collector,
        "read_lumberjack_pid",
        lambda name: {"orphan": 300, "dead": 400}.get(name),
    )

    snapshot = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert [row.name for row in snapshot.lumberjacks] == ["orphan", "zeta"]
    assert snapshot.lumberjacks[0].state == "orphaned"
    assert snapshot.lumberjacks[1].configured_chops == ("alpha", "beta")
    assert snapshot.state == "degraded"


def test_optional_file_and_directory_races_are_best_effort(monkeypatch) -> None:
    stopped_probe = _probe(
        lock_held=False,
        lock_pid=None,
        orchestrator_pid=None,
        legacy_pid=None,
    )
    _patch_host(monkeypatch, probe=stopped_probe, live_pids=set())

    def vanished(*_args, **_kwargs):
        raise FileNotFoundError("raced with collection")

    monkeypatch.setattr(collector, "read_desired_state", vanished)
    monkeypatch.setattr(collector, "read_maintenance", vanished)
    monkeypatch.setattr(collector, "read_recent_lifecycle_events", vanished)
    monkeypatch.setattr(collector, "list_lumberjack_names", vanished)

    snapshot = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert snapshot.state == "not_started"
    assert snapshot.health == "healthy"
    assert snapshot.latest_lifecycle_event is None


def test_required_config_and_runner_failures_become_error_snapshots(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        collector,
        "load_axe_config",
        lambda: (_ for _ in ()).throw(RuntimeError("broken config")),
    )

    config_error = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert (config_error.state, config_error.health, config_error.exit_code) == (
        "error",
        "error",
        2,
    )
    assert config_error.collection_error is not None
    assert config_error.collection_error.code == "config_read_failed"

    _patch_host(monkeypatch)
    monkeypatch.setattr(
        collector,
        "count_hook_runners_global",
        lambda: (_ for _ in ()).throw(OSError("runner store unavailable")),
    )
    runner_error = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert runner_error.collection_error is not None
    assert runner_error.collection_error.code == "runner_count_failed"


def test_binding_and_programming_failures_are_not_collection_errors(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        collector,
        "load_axe_config",
        lambda: (_ for _ in ()).throw(AttributeError("stale binding")),
    )

    with pytest.raises(AttributeError, match="stale binding"):
        collector.collect_axe_status_snapshot(clock=lambda: NOW)


def test_clock_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        collector.collect_axe_status_snapshot(
            clock=lambda: datetime(2026, 7, 23, 12, 0, 0)
        )


def test_collection_does_not_create_state_directories(monkeypatch, tmp_path) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setattr(collector, "load_axe_config", _config)
    monkeypatch.setattr(
        collector,
        "probe_orchestrator",
        lambda *, cleanup: _probe(
            lock_held=False,
            lock_pid=None,
            orchestrator_pid=None,
            legacy_pid=None,
        ),
    )
    monkeypatch.setattr(collector, "count_hook_runners_global", lambda: 0)
    monkeypatch.setattr(collector, "count_agent_runners_global", lambda: 0)

    snapshot = collector.collect_axe_status_snapshot(clock=lambda: NOW)

    assert snapshot.state == "not_started"
    assert not sase_home.exists()
