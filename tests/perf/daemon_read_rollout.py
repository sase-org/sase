"""Policy helpers for Epic 5 daemon-read rollout performance gates."""

from __future__ import annotations

from collections.abc import Mapping

EPIC5_TARGETS_MS = {
    "warm_cli_read_p95": 30.0,
    "ace_first_indexed_snapshot_p95": 250.0,
    "ace_no_change_refresh_p95": 5.0,
    "large_changespec_search_p95": 100.0,
    "large_agent_history_status_p95": 250.0,
}


def failing_perf_gates(metrics_ms: Mapping[str, float]) -> list[str]:
    """Return target names whose measured p95 exceeds the rollout budget."""

    failures: list[str] = []
    for name, budget_ms in EPIC5_TARGETS_MS.items():
        value = metrics_ms.get(name)
        if value is not None and value > budget_ms:
            failures.append(name)
    return failures
