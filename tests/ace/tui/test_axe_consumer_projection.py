"""Consumer-projection skip for heartbeat-only axe collects."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions.axe_display._data import AxeCollectedData
from sase.ace.tui.actions.axe_display._refresh_collect import (
    AxeRefreshCollectMixin,
    _axe_consumer_projection_from_app,
    _axe_consumer_projection_from_data,
)
from sase.axe.state import LumberjackMetrics, LumberjackStatus
from tests.ace.tui._axe_collector_helpers import make_metrics, make_status


def _status(**overrides: object) -> LumberjackStatus:
    status = make_status("hooks")
    for key, value in overrides.items():
        setattr(status, key, value)
    return status


def _metrics(**overrides: object) -> LumberjackMetrics:
    metrics = make_metrics()
    for key, value in overrides.items():
        setattr(metrics, key, value)
    return metrics


def _data(
    *,
    status: LumberjackStatus | None = None,
    metrics: LumberjackMetrics | None = None,
    include_full_snapshots: bool = False,
    axe_output: str = "",
    log_tails: dict[str, str] | None = None,
    service_status: object | None = None,
    axe_running: bool = True,
) -> AxeCollectedData:
    resolved_status = status if status is not None else _status()
    resolved_metrics = metrics if metrics is not None else _metrics()
    return AxeCollectedData(
        axe_running=axe_running,
        axe_output=axe_output,
        lumberjack_names=["hooks"],
        bgcmd_slots=[],
        lumberjack_statuses={"hooks": resolved_status},
        lumberjack_metrics={"hooks": resolved_metrics},
        lumberjack_log_tails=log_tails or {},
        bgcmd_details={},
        lumberjack_chop_names={},
        chop_snapshots={},
        lumberjack_snapshots={},
        include_full_snapshots=include_full_snapshots,
        service_status=service_status,  # type: ignore[arg-type]
    )


def _app_from_data(data: AxeCollectedData) -> SimpleNamespace:
    return SimpleNamespace(
        _axe_first_load_done=True,
        axe_running=data.axe_running,
        _axe_lumberjack_names=list(data.lumberjack_names),
        _axe_routine_origins={},
        _axe_lumberjack_statuses=dict(data.lumberjack_statuses),
        _axe_lumberjack_metrics=dict(data.lumberjack_metrics),
        _bgcmd_slots=list(data.bgcmd_slots),
        _service_status=data.service_status,
        _service_status_error=data.service_status_error,
        _axe_degraded_status=data.degraded_status,
        _axe_full_snapshot_ready=data.include_full_snapshots,
        current_tab="services" if data.include_full_snapshots else "agents",
        _axe_output=data.axe_output,
        _axe_lumberjack_log_tails=dict(data.lumberjack_log_tails),
        _axe_bgcmd_details=dict(data.bgcmd_details),
        _axe_chop_snapshots=dict(data.chop_snapshots),
    )


def test_heartbeat_fields_do_not_change_consumer_projection() -> None:
    baseline = _data(status=_status(uptime_seconds=1, last_tick_spawns=1))
    heartbeat = _data(
        status=_status(
            uptime_seconds=80,
            last_tick_spawns=4,
            last_tick_skipped=2,
            last_tick_no_ops=1,
        ),
        metrics=_metrics(
            last_tick_spawns=4,
            last_tick_at="later",
            spawn_samples=[[1.0, 2.0]],
        ),
    )
    assert _axe_consumer_projection_from_data(baseline) == (
        _axe_consumer_projection_from_data(heartbeat)
    )


def test_pid_and_cycle_changes_do_change_consumer_projection() -> None:
    baseline = _data(status=_status(pid=123, cycles_run=4))
    changed = _data(status=_status(pid=456, cycles_run=5))
    assert _axe_consumer_projection_from_data(baseline) != (
        _axe_consumer_projection_from_data(changed)
    )


def test_visible_log_changes_on_full_snapshots() -> None:
    baseline = _data(
        include_full_snapshots=True, axe_output="a\n", log_tails={"hooks": "a"}
    )
    changed = _data(
        include_full_snapshots=True, axe_output="a\nb\n", log_tails={"hooks": "a\nb"}
    )
    assert _axe_consumer_projection_from_data(baseline) != (
        _axe_consumer_projection_from_data(changed)
    )


def test_header_only_payloads_ignore_log_tails() -> None:
    baseline = _data(
        include_full_snapshots=False, axe_output="a\n", log_tails={"hooks": "a"}
    )
    changed = _data(
        include_full_snapshots=False, axe_output="a\nb\n", log_tails={"hooks": "a\nb"}
    )
    assert _axe_consumer_projection_from_data(baseline) == (
        _axe_consumer_projection_from_data(changed)
    )


def test_service_heartbeat_is_excluded_from_projection() -> None:
    host = SimpleNamespace(state="running", pid=9, error=None)
    first = _data(
        service_status=SimpleNamespace(
            host=host, procs=(), generated_at=1.0, heartbeat_at=1.0
        )
    )
    second = _data(
        service_status=SimpleNamespace(
            host=host, procs=(), generated_at=99.0, heartbeat_at=99.0
        )
    )
    assert _axe_consumer_projection_from_data(first) == (
        _axe_consumer_projection_from_data(second)
    )


def test_service_state_change_is_visible() -> None:
    first = _data(
        service_status=SimpleNamespace(
            host=SimpleNamespace(state="starting", pid=9, error=None),
            procs=(),
        )
    )
    second = _data(
        service_status=SimpleNamespace(
            host=SimpleNamespace(state="running", pid=9, error=None),
            procs=(),
        )
    )
    assert _axe_consumer_projection_from_data(first) != (
        _axe_consumer_projection_from_data(second)
    )


def test_matching_app_state_is_noop_after_first_load() -> None:
    data = _data(status=_status(uptime_seconds=12))
    app = _app_from_data(data)
    app.axe_running = data.axe_running
    assert _axe_consumer_projection_from_data(
        data
    ) == _axe_consumer_projection_from_app(app)
    assert AxeRefreshCollectMixin._axe_collected_data_is_noop(app, data) is True


def test_first_load_never_skips_apply() -> None:
    data = _data()
    app = _app_from_data(data)
    app._axe_first_load_done = False
    assert AxeRefreshCollectMixin._axe_collected_data_is_noop(app, data) is False
