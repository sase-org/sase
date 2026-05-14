"""Policy helpers for Epic 5 daemon-read rollout performance gates."""

from __future__ import annotations

from collections.abc import Mapping

from sase.daemon.read_config import (
    ACE_DAEMON_SURFACE_GROUPS,
    DEFAULT_ENABLED_SURFACE_GROUPS,
)

EPIC5_DEFAULT_SURFACE_GROUPS = (
    DEFAULT_ENABLED_SURFACE_GROUPS - ACE_DAEMON_SURFACE_GROUPS
)

EPIC5_TARGETS_MS = {
    "warm_cli_read_p95": 30.0,
    "ace_first_indexed_snapshot_p95": 250.0,
    "ace_no_change_refresh_p95": 5.0,
    "large_changespec_search_p95": 100.0,
    "large_agent_history_status_p95": 250.0,
}

EPIC5_ROLLOUT_PARITY_GATES = frozenset(
    {"daemon_read.parity.global"}
    | {f"daemon_read.parity.{surface}" for surface in EPIC5_DEFAULT_SURFACE_GROUPS}
)
EPIC5_ROLLOUT_PERF_GATES = frozenset(
    {"daemon_read.perf.global"}
    | {f"daemon_read.perf.{surface}" for surface in EPIC5_DEFAULT_SURFACE_GROUPS}
)


def failing_perf_gates(metrics_ms: Mapping[str, float]) -> list[str]:
    """Return target names whose measured p95 exceeds the rollout budget."""

    failures: list[str] = []
    for name, budget_ms in EPIC5_TARGETS_MS.items():
        value = metrics_ms.get(name)
        if value is not None and value > budget_ms:
            failures.append(name)
    return failures


__all__ = [
    "EPIC5_ROLLOUT_PARITY_GATES",
    "EPIC5_ROLLOUT_PERF_GATES",
    "EPIC5_DEFAULT_SURFACE_GROUPS",
    "EPIC5_TARGETS_MS",
    "failing_perf_gates",
]
