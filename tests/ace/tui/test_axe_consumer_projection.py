"""Consumer-projection skip for heartbeat-only axe collects."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions.axe_display._data import AxeCollectedData
from sase.ace.tui.actions.axe_display._refresh_collect import (
    AxeRefreshCollectMixin,
    _axe_consumer_projection_from_app,
    _axe_consumer_projection_from_data,
    _axe_header_projection_from_app,
    _axe_header_projection_from_data,
)
from sase.axe.state import LumberjackMetrics, LumberjackStatus
from tests.ace.tui._axe_collector_helpers import (
    make_bgcmd_info,
    make_metrics,
    make_status,
)


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
    service_status_error: str | None = None,
    bgcmd_slots: list[tuple[int, object]] | None = None,
    lumberjack_names: list[str] | None = None,
    axe_running: bool = True,
) -> AxeCollectedData:
    resolved_status = status if status is not None else _status()
    resolved_metrics = metrics if metrics is not None else _metrics()
    return AxeCollectedData(
        axe_running=axe_running,
        axe_output=axe_output,
        lumberjack_names=list(lumberjack_names) if lumberjack_names else ["hooks"],
        bgcmd_slots=list(bgcmd_slots) if bgcmd_slots else [],  # type: ignore[arg-type]
        lumberjack_statuses={"hooks": resolved_status},
        lumberjack_metrics={"hooks": resolved_metrics},
        lumberjack_log_tails=log_tails or {},
        bgcmd_details={},
        lumberjack_chop_names={},
        chop_snapshots={},
        lumberjack_snapshots={},
        include_full_snapshots=include_full_snapshots,
        service_status=service_status,  # type: ignore[arg-type]
        service_status_error=service_status_error,
    )


def _app_from_data(data: AxeCollectedData) -> SimpleNamespace:
    return SimpleNamespace(
        _axe_first_load_done=True,
        axe_running=data.axe_running,
        _axe_lumberjack_names=list(data.lumberjack_names),
        _axe_routine_origins=dict(data.routine_origins),
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
        _axe_lumberjack_snapshots={},
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


def _cycle_heartbeat(
    cycles_run: int, last_cycle: str, spawn_rate: float
) -> tuple[LumberjackStatus, LumberjackMetrics]:
    """One routine-cycle rewrite: same liveness, advanced progress heartbeat."""
    return (
        _status(
            pid=123,
            status="running",
            cycles_run=cycles_run,
            last_cycle=last_cycle,
            errors_encountered=0,
        ),
        _metrics(
            cycles_run=cycles_run,
            chops_executed=157,
            errors_encountered=0,
            spawn_rate_per_minute=spawn_rate,
        ),
    )


def test_header_projection_ignores_routine_cycle_heartbeat() -> None:
    """Observed live shape: every tick advances cycles/last_cycle/spawn rate.

    Nothing off the Services tab renders these fields, so a header-only
    collect must compare equal while the full Services compare still sees
    the rewrite.
    """
    first_status, first_metrics = _cycle_heartbeat(3280, "2026-11-22T20:27:50", 0.8)
    second_status, second_metrics = _cycle_heartbeat(3286, "2026-11-22T20:28:02", 0.6)
    first = _data(status=first_status, metrics=first_metrics)
    second = _data(status=second_status, metrics=second_metrics)
    assert _axe_header_projection_from_data(first) == (
        _axe_header_projection_from_data(second)
    )
    assert _axe_consumer_projection_from_data(first) != (
        _axe_consumer_projection_from_data(second)
    )


def test_header_projection_sees_liveness_and_roster_transitions() -> None:
    """Restarts, stops, errors, arrivals, and transitions still apply off-tab."""
    running_host = SimpleNamespace(state="running", pid=9, error=None)
    baseline = _data(
        service_status=SimpleNamespace(host=running_host, procs=()),
    )
    variants = [
        _data(
            service_status=SimpleNamespace(host=running_host, procs=()),
            status=_status(pid=456),
        ),
        _data(
            service_status=SimpleNamespace(host=running_host, procs=()),
            status=_status(status="error"),
        ),
        _data(
            service_status=SimpleNamespace(host=running_host, procs=()),
            status=_status(errors_encountered=2),
        ),
        _data(
            service_status=SimpleNamespace(host=running_host, procs=()),
            metrics=_metrics(errors_encountered=1),
        ),
        _data(
            service_status=SimpleNamespace(host=running_host, procs=()),
            axe_running=False,
        ),
        _data(
            service_status=SimpleNamespace(
                host=SimpleNamespace(state="starting", pid=9, error=None),
                procs=(),
            )
        ),
        _data(
            service_status=SimpleNamespace(host=running_host, procs=()),
            service_status_error="service status unavailable",
        ),
        _data(
            service_status=SimpleNamespace(host=running_host, procs=()),
            bgcmd_slots=[(1, make_bgcmd_info())],
        ),
        _data(
            service_status=SimpleNamespace(host=running_host, procs=()),
            lumberjack_names=["hooks", "checks"],
        ),
    ]
    alone = _axe_header_projection_from_data(baseline)
    for variant in variants:
        assert _axe_header_projection_from_data(variant) != alone


def test_header_noop_skips_heartbeat_but_full_compare_sees_it() -> None:
    """Mode matrix: heartbeat churn skips header applies, never full ones."""
    first_status, first_metrics = _cycle_heartbeat(3280, "2026-11-22T20:27:50", 0.8)
    second_status, second_metrics = _cycle_heartbeat(3286, "2026-11-22T20:28:02", 0.6)
    calm = _data(status=first_status, metrics=first_metrics)
    app = _app_from_data(calm)
    churned = _data(status=second_status, metrics=second_metrics)
    assert AxeRefreshCollectMixin._axe_collected_data_is_noop(app, churned) is True

    # The same churn on a full Services collect must still apply.
    calm_full = _data(
        status=first_status,
        metrics=first_metrics,
        include_full_snapshots=True,
    )
    app_full = _app_from_data(calm_full)
    churned_full = _data(
        status=second_status,
        metrics=second_metrics,
        include_full_snapshots=True,
    )
    assert (
        AxeRefreshCollectMixin._axe_collected_data_is_noop(app_full, churned_full)
        is False
    )
    assert (
        AxeRefreshCollectMixin._axe_collected_data_is_noop(app_full, calm_full) is True
    )

    # A header payload landing mid-Services-tab (in-flight tab-switch race)
    # compares by header fields and still skips the redundant apply.
    assert AxeRefreshCollectMixin._axe_collected_data_is_noop(app_full, churned) is True


def test_header_noop_refreshes_status_caches_without_rebuild() -> None:
    """Skipped header ticks keep Services-entry paint and full compares current."""
    first_status, first_metrics = _cycle_heartbeat(3280, "2026-11-22T20:27:50", 0.8)
    second_status, second_metrics = _cycle_heartbeat(3286, "2026-11-22T20:28:02", 0.6)
    calm = _data(status=first_status, metrics=first_metrics)
    app = _app_from_data(calm)
    app._axe_lumberjack_snapshots = {
        "hooks": SimpleNamespace(status=first_status, metrics=first_metrics)
    }
    churned = _data(status=second_status, metrics=second_metrics)
    assert AxeRefreshCollectMixin._axe_collected_data_is_noop(app, churned) is True
    AxeRefreshCollectMixin._refresh_axe_header_caches(app, churned)
    assert app._axe_lumberjack_statuses["hooks"] is second_status
    assert app._axe_lumberjack_metrics["hooks"] is second_metrics
    assert app._axe_lumberjack_snapshots["hooks"].status is second_status
    # The refreshed caches now agree with disk, so a full compare sees no
    # phantom status/metric drift beyond the genuine cycle rewrite.
    assert _axe_header_projection_from_app(app) == (
        _axe_header_projection_from_data(churned)
    )


def test_header_collect_across_cycle_rewrite_is_header_noop() -> None:
    """End-to-end collect: a routine-cycle rewrite skips the header apply.

    Drives the real ``collect_axe_status_data`` twice across one routine
    cycle (the ordinary-host heartbeat shape: same liveness, advanced
    ``cycles_run``/``last_cycle``) and checks the second payload against
    app state built from the first.
    """
    from unittest.mock import patch

    from sase.ace.tui.actions.axe_display import collect_axe_status_data

    from tests.ace.tui._axe_collector_helpers import (
        FakeAxeConfig,
        lumberjack_config,
        patch_service_status,
    )

    first_status = make_status("hooks")
    first_status.cycles_run = 3280
    first_status.last_cycle = "2026-11-22T20:27:50-05:00"
    second_status = make_status("hooks")
    second_status.cycles_run = 3286
    second_status.last_cycle = "2026-11-22T20:28:02-05:00"
    first_metrics = make_metrics()
    second_metrics = make_metrics()
    second_metrics.spawn_rate_per_minute = 0.6
    config = FakeAxeConfig({"hooks": lumberjack_config("hooks", [])})

    with (
        patch_service_status("running"),
        patch("sase.axe.config.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_bgcmd_slots",
            return_value={},
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_status",
            side_effect=[first_status, second_status],
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_metrics",
            side_effect=[first_metrics, second_metrics],
        ),
    ):
        first = collect_axe_status_data(include_full_snapshots=False)
        second = collect_axe_status_data(include_full_snapshots=False)

    app = _app_from_data(first)
    assert AxeRefreshCollectMixin._axe_collected_data_is_noop(app, second) is True
    assert _axe_consumer_projection_from_data(first) != (
        _axe_consumer_projection_from_data(second)
    )


def test_spawn_rate_decays_between_reads_at_fixed_files() -> None:
    """Pin the wall-clock mechanism: identical files, different recomputed rate.

    ``read_lumberjack_metrics`` recomputes ``spawn_rate_per_minute`` at read
    time, so the full projection drifts between ticks even when no file
    changed. The header projection must not carry this field.
    """
    from sase.axe.spawn_rate import spawn_rate_per_minute

    samples = [[1000.0, 2.0]]
    early = spawn_rate_per_minute(
        samples, now=1010.0, window_seconds=300.0, since=700.0
    )
    late = spawn_rate_per_minute(samples, now=1400.0, window_seconds=300.0, since=700.0)
    assert early != late
