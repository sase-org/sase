"""Rollout gate tests for Epic 7 daemon scheduler enablement."""

from __future__ import annotations

from tests.perf.daemon_scheduler_rollout import (
    EPIC7_SCHEDULER_TARGETS_MS,
    failing_scheduler_perf_gates,
)


def test_epic7_scheduler_perf_gate_names_cover_rollout_targets() -> None:
    assert set(EPIC7_SCHEDULER_TARGETS_MS) == {
        "launch_fanout_submit_p95",
        "ace_launch_responsiveness_p95",
        "mobile_launch_latency_p95",
        "scheduler_restart_recovery_p95",
        "bulk_kill_submit_p95",
        "axe_tick_throughput_p95",
    }


def test_failing_scheduler_perf_gates_reports_only_exceeded_targets() -> None:
    metrics = {
        "launch_fanout_submit_p95": EPIC7_SCHEDULER_TARGETS_MS[
            "launch_fanout_submit_p95"
        ],
        "bulk_kill_submit_p95": (
            EPIC7_SCHEDULER_TARGETS_MS["bulk_kill_submit_p95"] + 1.0
        ),
    }

    assert failing_scheduler_perf_gates(metrics) == ["bulk_kill_submit_p95"]
