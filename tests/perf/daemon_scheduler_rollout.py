"""Rollout gate helpers for Epic 7 daemon scheduler enablement."""

from __future__ import annotations

EPIC7_SCHEDULER_TARGETS_MS: dict[str, float] = {
    "launch_fanout_submit_p95": 50.0,
    "ace_launch_responsiveness_p95": 100.0,
    "mobile_launch_latency_p95": 150.0,
    "scheduler_restart_recovery_p95": 250.0,
    "bulk_kill_submit_p95": 100.0,
    "axe_tick_throughput_p95": 250.0,
}

EPIC7_ROLLOUT_PARITY_GATES = frozenset(
    {
        "scheduler.launch.parity",
        "scheduler.lifecycle.parity",
        "scheduler.axe.parity",
    }
)
EPIC7_ROLLOUT_PERF_GATES = frozenset(
    {
        "scheduler.launch.perf",
        "scheduler.lifecycle.perf",
        "scheduler.axe.perf",
    }
)


def failing_scheduler_perf_gates(metrics: dict[str, float]) -> list[str]:
    """Return Epic 7 scheduler rollout gates whose reported values exceed target."""

    return [
        name
        for name, target_ms in EPIC7_SCHEDULER_TARGETS_MS.items()
        if metrics.get(name, 0.0) > target_ms
    ]


__all__ = [
    "EPIC7_ROLLOUT_PARITY_GATES",
    "EPIC7_ROLLOUT_PERF_GATES",
    "EPIC7_SCHEDULER_TARGETS_MS",
    "failing_scheduler_perf_gates",
]
