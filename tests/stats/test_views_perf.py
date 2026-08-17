from dataclasses import FrozenInstanceError

import pytest
from pytest import MonkeyPatch

from sase.stats._perf_view import (
    STARTUP_CRITICAL_SECONDS,
    STARTUP_WARN_SECONDS,
    build_perf_view,
)
from sase.stats.ranges import StatsRange
from sase.telemetry._config import HealthThresholds
from tests.stats._views_payloads import (
    perf_logs_payload,
    perf_telemetry_payload,
    perf_telemetry_provider_payload,
)


def _range(start_ts: int = 1_000, end_ts: int = 2_000) -> StatsRange:
    return StatsRange(start_ts, end_ts, "span", "Last hour")


def test_build_perf_view_maps_logs_and_telemetry() -> None:
    view = build_perf_view(
        perf_logs_payload(),
        perf_telemetry_payload(),
        selected_range=_range(),
        now=2_000.0,
    )

    assert view.available is True
    assert view.group_by == "subsystem"
    assert view.startup.sessions == 3
    assert view.startup.stages[2].label == "visible ready"
    assert view.startup.tile.value == 1.5
    assert view.startup.tile.status == "ok"
    assert view.startup.sparkline == (1.2, 1.5, 4.0)
    assert view.startup.slowest is not None
    assert view.startup.slowest.initial_tab == "agents"

    assert view.stalls.available is True
    assert view.stalls.stall_count == 1
    assert view.stalls.hitch_count == 2
    assert view.stalls.worst_seconds == 3.2
    assert view.stalls.tile.status == "critical"
    assert view.stalls.tile.detail == "2 hitches · worst 3.2s"
    assert view.stalls.tile.value == 1.0
    assert view.stalls.tile.sample_count == 3
    assert view.stalls.events[2].suppressed_count == 5
    assert view.stalls.top_contexts[0].name == "agents"

    assert view.launches.count == 4
    assert view.launches.tile.value == 450.0
    assert view.launches.tile.status is None
    assert view.launches.tile.detail == "4 launches · 2 slow stages"

    assert [row.label for row in view.latency.rows] == [
        "Agent runs",
        "LLM calls",
        "Hooks",
        "Workflows",
        "Axe cycles",
    ]
    agent = view.latency.rows[0]
    assert agent.p95 == 120.0
    assert agent.count == 20
    assert agent.error_rate == pytest.approx(5.0)
    llm = view.latency.rows[1]
    assert llm.retry_rate == pytest.approx(8.0)
    assert view.latency.agent_tile.detail == "20 runs"
    assert view.latency.llm_tile.detail == "err 5% · retry 8%"
    assert [tile.key for tile in view.tiles] == [
        "startup",
        "stalls",
        "launch",
        "agent_p95",
        "llm_p95",
    ]

    assert view.coverage.telemetry.resolution == "raw"
    assert view.coverage.telemetry.last_write_age_seconds == 100.0
    assert view.coverage.telemetry.last_write_by_subsystem == (
        ("agent", 1_900),
        ("llm", 1_850),
    )
    assert "1 unreadable records skipped" in view.coverage.notes
    assert any("launch_timing" in note for note in view.coverage.notes)
    git_ops = next(entry for entry in view.coverage.logs if entry.source == "git_ops")
    assert git_ops.present is False


def test_startup_status_thresholds() -> None:
    just_ok = _startup_view(STARTUP_WARN_SECONDS - 0.001)
    at_warn = _startup_view(STARTUP_WARN_SECONDS)
    just_warn = _startup_view(STARTUP_CRITICAL_SECONDS - 0.001)
    at_critical = _startup_view(STARTUP_CRITICAL_SECONDS)

    assert just_ok.startup.tile.status == "ok"
    assert at_warn.startup.tile.status == "warning"
    assert just_warn.startup.tile.status == "warning"
    assert at_critical.startup.tile.status == "critical"


def test_stall_status_thresholds() -> None:
    none = _stalls_view(stalls=0, hitches=0)
    hitch = _stalls_view(stalls=0, hitches=1)
    stall = _stalls_view(stalls=1, hitches=0)

    assert none.stalls.available is False
    assert none.stalls.tile.status is None
    assert hitch.stalls.tile.status == "warning"
    assert stall.stalls.tile.status == "critical"


def test_latency_status_uses_health_thresholds() -> None:
    thresholds = HealthThresholds(
        p95_latency_warn=300.0,
        p95_latency_critical=600.0,
        error_rate_warn=10.0,
        error_rate_critical=25.0,
    )
    ok = _agent_view(p95=299.9, errors=9, total=100, thresholds=thresholds)
    warn_p95 = _agent_view(p95=300.0, errors=0, total=100, thresholds=thresholds)
    crit_p95 = _agent_view(p95=600.0, errors=0, total=100, thresholds=thresholds)
    warn_err = _agent_view(p95=10.0, errors=10, total=100, thresholds=thresholds)
    crit_err = _agent_view(p95=10.0, errors=25, total=100, thresholds=thresholds)

    assert ok.latency.agent_tile.status == "ok"
    assert warn_p95.latency.agent_tile.status == "warning"
    assert crit_p95.latency.agent_tile.status == "critical"
    assert warn_err.latency.agent_tile.status == "warning"
    assert crit_err.latency.agent_tile.status == "critical"


def test_delta_ratio_against_previous_window() -> None:
    previous_logs = perf_logs_payload()
    previous_logs["startup"]["stages"][2]["summary"]["p50"] = 1.0  # type: ignore[index]
    previous_telemetry = perf_telemetry_payload()
    previous_telemetry["histograms"]["sase_agent_run_duration_seconds"]["p95"] = {  # type: ignore[index]
        "resolution": "raw",
        "series": [{"labels": {}, "value": 80.0}],
    }

    view = build_perf_view(
        perf_logs_payload(),
        perf_telemetry_payload(),
        selected_range=_range(),
        previous_perf_payload=previous_logs,
        previous_telemetry_payload=previous_telemetry,
    )

    assert view.startup.tile.delta_ratio == pytest.approx(0.5)
    assert view.latency.agent_tile.delta_ratio == pytest.approx(0.5)
    assert view.latency.llm_tile.delta_ratio is None


def test_disabled_telemetry_keeps_log_sections() -> None:
    view = build_perf_view(
        perf_logs_payload(),
        {"enabled": False, "group_by": "subsystem"},
        selected_range=_range(),
    )

    assert view.startup.available is True
    assert view.stalls.available is True
    assert view.launches.available is True
    assert view.latency.available is False
    assert view.latency.rows == ()
    assert view.latency.agent_tile.available is False
    assert view.latency.llm_tile.available is False
    assert view.coverage.telemetry.enabled is False
    assert "Telemetry is disabled (telemetry.enabled)." in view.coverage.notes


def test_empty_payloads_are_unavailable_but_typed() -> None:
    view = build_perf_view({}, {}, selected_range=_range())

    assert view.startup.available is False
    assert view.stalls.available is False
    assert view.launches.available is False
    assert view.latency.available is False
    assert view.startup.stages == ()
    assert view.coverage.logs == ()
    assert view.tiles[0].value is None


def test_all_time_range_adds_retention_note() -> None:
    view = build_perf_view(
        {},
        {"enabled": False},
        selected_range=_range(start_ts=0, end_ts=100),
    )

    assert any("All time" in note for note in view.coverage.notes)


def test_provider_group_merges_rows_and_tokens() -> None:
    view = build_perf_view(
        perf_logs_payload(),
        perf_telemetry_provider_payload(),
        selected_range=_range(),
        group_by="provider",
    )

    assert view.group_by == "provider"
    assert [row.key for row in view.latency.rows] == ["codex", "claude"]
    codex = view.latency.rows[0]
    assert codex.p95 == 6.0
    assert codex.count == 80
    assert codex.error_rate == pytest.approx(2.5)
    assert codex.tokens_in == 800
    assert codex.tokens_out == 300
    assert codex.cache_read_tokens == 200
    assert codex.cache_read_share == pytest.approx(0.2)
    claude = view.latency.rows[1]
    assert claude.error_rate == pytest.approx(20.0)
    assert claude.status == "warning"


def test_workflow_group_uses_agent_and_workflow_metrics() -> None:
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

    view = build_perf_view(
        {},
        telemetry,
        selected_range=_range(),
        group_by="workflow",
    )

    assert len(view.latency.rows) == 1
    row = view.latency.rows[0]
    assert row.label == "review"
    assert row.p95 == 50.0
    assert row.count == 4
    assert row.error_rate == pytest.approx(25.0)
    assert row.status == "critical"


def test_probe_env_vars_are_reported(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)

    view = build_perf_view({}, {"enabled": False}, selected_range=_range())

    by_name = {probe.name: probe.enabled for probe in view.coverage.probes}
    assert by_name["SASE_TUI_PERF"] is True
    assert by_name["SASE_TUI_TRACE"] is False
    assert all("Set SASE_TUI_" in probe.hint for probe in view.coverage.probes)


def test_perf_view_is_frozen() -> None:
    view = build_perf_view(
        perf_logs_payload(),
        perf_telemetry_payload(),
        selected_range=_range(),
    )

    with pytest.raises(FrozenInstanceError):
        view.startup.sessions = 99  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        view.tiles[0].value = 0.0  # type: ignore[misc]


def _startup_view(median: float):
    payload = perf_logs_payload()
    payload["startup"]["stages"][2]["summary"]["p50"] = median  # type: ignore[index]
    return build_perf_view(payload, {"enabled": False}, selected_range=_range())


def _stalls_view(*, stalls: int, hitches: int):
    payload = {
        "stalls": {
            "events": [
                {
                    "event": "tui_stall",
                    "count": stalls,
                    "worst_seconds": 1.0 if stalls else None,
                },
                {
                    "event": "tui_hitch",
                    "count": hitches,
                    "worst_seconds": 0.2 if hitches else None,
                },
            ],
            "top_contexts": [],
            "recovery_count": 0,
        }
    }
    return build_perf_view(payload, {"enabled": False}, selected_range=_range())


def _agent_view(
    *,
    p95: float,
    errors: float,
    total: float,
    thresholds: HealthThresholds,
):
    telemetry = {
        "enabled": True,
        "histograms": {
            "sase_agent_run_duration_seconds": {
                "p95": {"series": [{"labels": {}, "value": p95}]},
            }
        },
        "counters": {
            "sase_agent_runs_total": {"series": [{"labels": {}, "value": total}]},
            "sase_agent_runs_total:error": {
                "series": [{"labels": {}, "value": errors}]
            },
        },
    }
    return build_perf_view(
        {},
        telemetry,
        selected_range=_range(),
        health_thresholds=thresholds,
    )
