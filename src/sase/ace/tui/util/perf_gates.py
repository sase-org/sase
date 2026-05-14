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


@dataclass(frozen=True)
class _AceM2ReadPerfBudget:
    """Direct-vs-daemon budget for one ACE daemon read surface."""

    surface: str
    perf_gate: str
    daemon_scenarios: tuple[str, ...]
    direct_scenarios: tuple[str, ...]
    absolute_p95_ms: float
    max_daemon_to_direct_ratio: float = 1.0


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

ACE_M2_READ_PERF_BUDGETS: dict[str, _AceM2ReadPerfBudget] = {
    "ace_agents": _AceM2ReadPerfBudget(
        surface="ace_agents",
        perf_gate="ace_daemon_read.perf.ace_agents",
        daemon_scenarios=("daemon_ace_agents_snapshot",),
        direct_scenarios=("direct_ace_agents_snapshot",),
        absolute_p95_ms=250.0,
    ),
    "ace_changespecs": _AceM2ReadPerfBudget(
        surface="ace_changespecs",
        perf_gate="ace_daemon_read.perf.ace_changespecs",
        daemon_scenarios=("daemon_changespec_snapshot",),
        direct_scenarios=("direct_changespec_snapshot",),
        absolute_p95_ms=250.0,
    ),
    "ace_notifications": _AceM2ReadPerfBudget(
        surface="ace_notifications",
        perf_gate="ace_daemon_read.perf.ace_notifications",
        daemon_scenarios=(
            "daemon_notification_counts",
            "daemon_notification_first_page",
        ),
        direct_scenarios=(
            "direct_notification_counts",
            "direct_notification_first_page",
        ),
        absolute_p95_ms=250.0,
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


def ace_m2_read_perf_gate_results(
    report: Mapping[str, Any],
    *,
    budgets: Mapping[str, _AceM2ReadPerfBudget] = ACE_M2_READ_PERF_BUDGETS,
) -> dict[str, dict[str, Any]]:
    """Return rollout perf gate statuses from an ACE direct-vs-daemon report."""

    results: dict[str, dict[str, Any]] = {}
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, Mapping):
        return {
            budget.perf_gate: {
                "status": "missing",
                "surface": surface,
                "reason": "report has no scenarios object",
            }
            for surface, budget in budgets.items()
        }

    for surface, budget in budgets.items():
        daemon_p95 = _max_scenario_p95(scenarios, budget.daemon_scenarios)
        direct_p95 = _max_scenario_p95(scenarios, budget.direct_scenarios)
        missing = [
            name
            for name in (*budget.daemon_scenarios, *budget.direct_scenarios)
            if not _scenario_has_p95(scenarios, name)
        ]
        if missing or daemon_p95 is None or direct_p95 is None:
            results[budget.perf_gate] = {
                "status": "missing",
                "surface": surface,
                "missing_scenarios": missing,
            }
            continue
        ratio = daemon_p95 / direct_p95 if direct_p95 > 0 else float("inf")
        daemon_fallbacks = _daemon_scenario_fallbacks(
            scenarios,
            budget.daemon_scenarios,
        )
        passes = not daemon_fallbacks and (
            daemon_p95 <= budget.absolute_p95_ms
            and ratio <= budget.max_daemon_to_direct_ratio
        )
        results[budget.perf_gate] = {
            "status": "ok" if passes else "blocked",
            "surface": surface,
            "fallback_scenarios": daemon_fallbacks,
            "daemon_p95_ms": daemon_p95,
            "direct_p95_ms": direct_p95,
            "max_daemon_to_direct_ratio": budget.max_daemon_to_direct_ratio,
            "daemon_to_direct_ratio": ratio,
            "absolute_p95_budget_ms": budget.absolute_p95_ms,
        }
    return results


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
    *,
    gated_surfaces: Iterable[str] = ACE_M2_SURFACE_GATES,
) -> list[str]:
    """Return enabled ACE daemon surfaces missing explicit M2 gate coverage."""

    gated = set(gated_surfaces)
    return sorted(
        surface
        for surface in ACE_DAEMON_SURFACE_GROUPS
        if surface_enabled(surface) and surface not in gated
    )


def _is_daemon_no_change_refresh_record(record: Mapping[str, Any]) -> bool:
    refresh_kind = record.get("refresh_kind")
    return bool(record.get("daemon_backed")) and refresh_kind in {
        "no_change",
        "auto_refresh_idle",
    }


def _max_scenario_p95(
    scenarios: Mapping[str, Any],
    names: Iterable[str],
) -> float | None:
    values: list[float] = []
    for name in names:
        value = _scenario_p95(scenarios, name)
        if value is not None:
            values.append(value)
    return max(values) if values else None


def _scenario_has_p95(scenarios: Mapping[str, Any], name: str) -> bool:
    return _scenario_p95(scenarios, name) is not None


def _scenario_p95(scenarios: Mapping[str, Any], name: str) -> float | None:
    scenario = scenarios.get(name)
    if not isinstance(scenario, Mapping):
        return None
    value = scenario.get("p95_ms")
    if isinstance(value, int | float):
        return float(value)
    return None


def _daemon_scenario_fallbacks(
    scenarios: Mapping[str, Any],
    names: Iterable[str],
) -> list[str]:
    fallbacks: list[str] = []
    for name in names:
        scenario = scenarios.get(name)
        if not isinstance(scenario, Mapping):
            continue
        summary = scenario.get("summary")
        if isinstance(summary, Mapping) and summary.get("used_daemon") is False:
            fallbacks.append(name)
    return fallbacks


__all__ = [
    "ACE_M2_READ_PERF_BUDGETS",
    "EPIC9_DAEMON_NO_CHANGE_FORBIDDEN_SPANS",
    "EPIC9_ROLLOUT_PARITY_GATES",
    "EPIC9_ROLLOUT_PERF_GATES",
    "EPIC9_TUI_TARGETS",
    "ACE_M2_SURFACE_GATES",
    "Epic9PerfTarget",
    "ace_m2_read_perf_gate_results",
    "ace_default_rollout_violations",
    "failing_epic9_perf_gates",
    "forbidden_daemon_no_change_refresh_spans",
]
