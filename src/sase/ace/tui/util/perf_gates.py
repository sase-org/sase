"""Epic 9 ACE virtualization rollout gates."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sase.daemon.read_config import ACE_DAEMON_SURFACE_GROUPS

GateDirection = Literal["max", "min"]


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
@dataclass(frozen=True)
class Epic9PerfTarget:
    """One measurable target for ACE daemon-read rollout."""

    name: str
    budget: float
    unit: str
    direction: GateDirection = "max"

    def fails(self, value: float) -> bool:
        if self.direction == "min":
            return value < self.budget
        return value > self.budget


@dataclass(frozen=True)
class _AceM2SurfaceGate:
    """Per-surface gate bundle required before ACE daemon-read promotion."""

    surface: str
    provider_contracts: tuple[str, ...]
    trace_assertions: tuple[str, ...]
    fallback_tests: tuple[str, ...]
    parity_gate: str
    perf_gate: str


EPIC9_TUI_TARGETS: dict[str, Epic9PerfTarget] = {
    "ace_shell_first_useful_paint_p95_ms": Epic9PerfTarget(
        "ace_shell_first_useful_paint_p95_ms", 500.0, "ms"
    ),
    "ace_agents_first_indexed_snapshot_p95_ms": Epic9PerfTarget(
        "ace_agents_first_indexed_snapshot_p95_ms", 250.0, "ms"
    ),
    "ace_changespecs_first_indexed_snapshot_p95_ms": Epic9PerfTarget(
        "ace_changespecs_first_indexed_snapshot_p95_ms", 250.0, "ms"
    ),
    "ace_notifications_first_indexed_snapshot_p95_ms": Epic9PerfTarget(
        "ace_notifications_first_indexed_snapshot_p95_ms", 250.0, "ms"
    ),
    "ace_agents_jk_key_to_paint_p95_ms": Epic9PerfTarget(
        "ace_agents_jk_key_to_paint_p95_ms", 16.0, "ms"
    ),
    "ace_changespecs_jk_key_to_paint_p95_ms": Epic9PerfTarget(
        "ace_changespecs_jk_key_to_paint_p95_ms", 16.0, "ms"
    ),
    "ace_no_change_auto_refresh_p95_ms": Epic9PerfTarget(
        "ace_no_change_auto_refresh_p95_ms", 5.0, "ms"
    ),
    "ace_broad_loader_call_count": Epic9PerfTarget(
        "ace_broad_loader_call_count", 0.0, "count"
    ),
    "ace_changespec_query_edit_large_p95_ms": Epic9PerfTarget(
        "ace_changespec_query_edit_large_p95_ms", 100.0, "ms"
    ),
    "ace_agent_history_query_edit_large_p95_ms": Epic9PerfTarget(
        "ace_agent_history_query_edit_large_p95_ms", 250.0, "ms"
    ),
    "ace_lazy_detail_stale_cancellation_count": Epic9PerfTarget(
        "ace_lazy_detail_stale_cancellation_count", 1.0, "count", "min"
    ),
}

EPIC9_DAEMON_NO_CHANGE_FORBIDDEN_SPANS = frozenset(
    {
        "agents.load_from_disk",
        "changespec.filter",
        "notification.snapshot.full_load",
        "artifact.archive.full_scan",
    }
)

EPIC9_ROLLOUT_PARITY_GATES = frozenset(
    f"ace_daemon_read.parity.{surface}" for surface in ACE_DAEMON_SURFACE_GROUPS
)
EPIC9_ROLLOUT_PERF_GATES = frozenset(
    f"ace_daemon_read.perf.{surface}" for surface in ACE_DAEMON_SURFACE_GROUPS
)

ACE_M2_SURFACE_GATES: dict[str, _AceM2SurfaceGate] = {
    "ace_agents": _AceM2SurfaceGate(
        surface="ace_agents",
        provider_contracts=("pages", "snapshots", "deltas", "lazy_details"),
        trace_assertions=(
            "ace.provider_snapshot",
            "ace_no_change_refresh.no_broad_loader",
            "ace_agents_first_indexed_snapshot_p95_ms",
            "ace_agents_jk_key_to_paint_p95_ms",
        ),
        fallback_tests=(
            "daemon_unavailable",
            "projection_degraded",
            "unsupported_capability",
            "surface_disabled",
            "stale_detail_cancellation",
        ),
        parity_gate="ace_daemon_read.parity.ace_agents",
        perf_gate="ace_daemon_read.perf.ace_agents",
    ),
    "ace_changespecs": _AceM2SurfaceGate(
        surface="ace_changespecs",
        provider_contracts=("pages", "snapshots", "lazy_details", "bounded_refresh"),
        trace_assertions=(
            "ace.provider_snapshot",
            "ace_no_change_refresh.no_broad_loader",
            "ace_changespecs_first_indexed_snapshot_p95_ms",
            "ace_changespecs_jk_key_to_paint_p95_ms",
        ),
        fallback_tests=(
            "daemon_unavailable",
            "projection_degraded",
            "unsupported_capability",
            "surface_disabled",
            "stale_detail_cancellation",
        ),
        parity_gate="ace_daemon_read.parity.ace_changespecs",
        perf_gate="ace_daemon_read.perf.ace_changespecs",
    ),
    "ace_notifications": _AceM2SurfaceGate(
        surface="ace_notifications",
        provider_contracts=("pages", "snapshots", "counts", "lazy_details"),
        trace_assertions=(
            "ace.provider_snapshot",
            "ace_no_change_refresh.no_broad_loader",
            "ace_notifications_first_indexed_snapshot_p95_ms",
        ),
        fallback_tests=(
            "daemon_unavailable",
            "projection_degraded",
            "unsupported_capability",
            "surface_disabled",
        ),
        parity_gate="ace_daemon_read.parity.ace_notifications",
        perf_gate="ace_daemon_read.perf.ace_notifications",
    ),
    "ace_artifacts": _AceM2SurfaceGate(
        surface="ace_artifacts",
        provider_contracts=("snapshots", "bounded_detail", "lazy_details"),
        trace_assertions=(
            "ace.provider_snapshot",
            "ace_no_change_refresh.no_broad_loader",
        ),
        fallback_tests=(
            "daemon_unavailable",
            "projection_degraded",
            "unsupported_capability",
            "surface_disabled",
            "stale_detail_cancellation",
        ),
        parity_gate="ace_daemon_read.parity.ace_artifacts",
        perf_gate="ace_daemon_read.perf.ace_artifacts",
    ),
    "ace_archive_search": _AceM2SurfaceGate(
        surface="ace_archive_search",
        provider_contracts=("pages", "snapshots", "bounded_refresh"),
        trace_assertions=(
            "ace.provider_snapshot",
            "ace_no_change_refresh.no_broad_loader",
            "ace_agent_history_query_edit_large_p95_ms",
        ),
        fallback_tests=(
            "daemon_unavailable",
            "projection_degraded",
            "unsupported_capability",
            "surface_disabled",
        ),
        parity_gate="ace_daemon_read.parity.ace_archive_search",
        perf_gate="ace_daemon_read.perf.ace_archive_search",
    ),
}


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
def failing_epic9_perf_gates(metrics: Mapping[str, float]) -> list[str]:
    """Return Epic 9 target names whose supplied metric misses the budget."""

    failures: list[str] = []
    for name, target in EPIC9_TUI_TARGETS.items():
        value = metrics.get(name)
        if value is not None and target.fails(value):
            failures.append(name)
    return failures


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
def forbidden_daemon_no_change_refresh_spans(
    records: Iterable[Mapping[str, Any]],
    *,
    forbidden_spans: Iterable[str] = EPIC9_DAEMON_NO_CHANGE_FORBIDDEN_SPANS,
) -> list[str]:
    """Return broad-loader spans observed during daemon-backed no-change refresh."""

    forbidden = set(forbidden_spans)
    matches: list[str] = []
    for record in records:
        if not _is_daemon_no_change_refresh_record(record):
            continue
        span = record.get("span")
        if isinstance(span, str) and span in forbidden:
            matches.append(span)
    return matches


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
def ace_default_rollout_violations(
    surface_enabled: Callable[[str], bool],
) -> list[str]:
    """Return ACE daemon surfaces that are enabled before explicit gate coverage."""

    return sorted(
        surface for surface in ACE_DAEMON_SURFACE_GROUPS if surface_enabled(surface)
    )


def _is_daemon_no_change_refresh_record(record: Mapping[str, Any]) -> bool:
    refresh_kind = record.get("refresh_kind")
    return bool(record.get("daemon_backed")) and refresh_kind in {
        "no_change",
        "auto_refresh_idle",
    }


__all__ = [
    "EPIC9_DAEMON_NO_CHANGE_FORBIDDEN_SPANS",
    "EPIC9_ROLLOUT_PARITY_GATES",
    "EPIC9_ROLLOUT_PERF_GATES",
    "EPIC9_TUI_TARGETS",
    "ACE_M2_SURFACE_GATES",
    "Epic9PerfTarget",
    "ace_default_rollout_violations",
    "failing_epic9_perf_gates",
    "forbidden_daemon_no_change_refresh_spans",
]
