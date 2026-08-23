"""Budget loading and evaluation for suite-cost recordings."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from tests._test_cost_records import (
    TEST_COST_SCHEMA,
    _cause_count,
    _cause_cpu_seconds,
    _cause_seconds,
    _summary_value,
)

_SEVERITIES = ("hard", "advisory")

# Summary metrics whose family is CPU (hard by default, and checked against
# the `cpu` tolerance rather than the ci/local wall tolerance).
_CPU_SUMMARY_METRICS = frozenset({"total_file_cpu_seconds", "collection_cpu_seconds"})
# Summary metrics whose family is memory (hard by default, wall tolerance).
_MEMORY_SUMMARY_METRICS = frozenset(
    {"peak_worker_rss_kib", "median_worker_rss_kib", "post_collection_worker_rss_kib"}
)
# Wall summary metric -> its CPU counterpart, for advisory annotations.
_WALL_TO_CPU_SUMMARY: Mapping[str, str] = {
    "total_file_wall_seconds": "total_file_cpu_seconds",
    "collection_seconds": "collection_cpu_seconds",
}


class CostBudgetFailure(NamedTuple):
    """One suite-cost metric that exceeded its committed budget."""

    metric: str
    actual: float
    limit: float
    tolerance: float
    severity: str

    @property
    def allowed(self) -> float:
        return self.limit * (1.0 + self.tolerance)

    def format(self) -> str:
        return (
            f"[{self.severity}] {self.metric}: actual {self.actual:.3f} exceeds "
            f"budget {self.limit:.3f} + {self.tolerance:.0%} tolerance "
            f"({self.allowed:.3f})"
        )


def load_cost_budgets(path: Path) -> dict[str, Any]:
    """Load and validate a committed suite-cost budget file."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != TEST_COST_SCHEMA:
        raise ValueError(f"{path} is not a schema-{TEST_COST_SCHEMA} cost budget")
    if not isinstance(payload.get("summary"), Mapping):
        raise ValueError(f"{path} has no summary budget object")
    if not isinstance(payload.get("causes", {}), Mapping):
        raise ValueError(f"{path} has an invalid causes budget object")
    return payload


def _budget_tolerance(budgets: Mapping[str, Any], *, ci: bool) -> float:
    raw_tolerance = budgets.get("tolerance", 0.15)
    if isinstance(raw_tolerance, Mapping):
        key = "ci" if ci else "local"
        raw_tolerance = raw_tolerance.get(key, raw_tolerance.get("default", 0.15))
    try:
        tolerance = float(raw_tolerance)
    except (TypeError, ValueError):
        tolerance = 0.15
    return max(tolerance, 0.0)


def _cpu_tolerance(budgets: Mapping[str, Any]) -> float:
    raw_tolerance = budgets.get("tolerance", {})
    raw_cpu = (
        raw_tolerance.get("cpu", 0.25) if isinstance(raw_tolerance, Mapping) else 0.25
    )
    try:
        return max(float(raw_cpu), 0.0)
    except (TypeError, ValueError):
        return 0.25


def _budget_dimension(raw_budget: object, key: str) -> float | None:
    """Extract one dimension's limit from a budget entry.

    ``key == "limit"`` also accepts a bare number, for budget entries that
    predate multi-dimension causes.
    """

    if isinstance(raw_budget, Mapping):
        raw_value: Any = raw_budget.get(key)
    elif key == "limit":
        raw_value = raw_budget
    else:
        raw_value = None
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def _resolve_severity(raw_budget: object, enforce_key: str, default: str) -> str:
    if isinstance(raw_budget, Mapping):
        enforce = raw_budget.get(enforce_key)
        if enforce in _SEVERITIES:
            return str(enforce)
    return default


def _summary_default_severity(metric: str) -> str:
    if metric in _CPU_SUMMARY_METRICS or metric in _MEMORY_SUMMARY_METRICS:
        return "hard"
    return "advisory"


def worker_divisor(record: Mapping[str, Any]) -> int:
    """Resolve how many workers a per-worker summary metric was summed over."""

    worker_count = record.get("worker_count")
    if isinstance(worker_count, (int, float)) and not isinstance(worker_count, bool):
        if worker_count >= 1:
            return int(worker_count)
    workers = record.get("workers")
    if isinstance(workers, Sequence):
        reporting = sum(
            1
            for worker in workers
            if isinstance(worker, Mapping)
            and worker.get("collection_seconds") is not None
        )
        if reporting:
            return reporting
    return 1


def check_cost_budgets(
    record: Mapping[str, Any],
    budgets: Mapping[str, Any],
    *,
    ci: bool = False,
) -> list[CostBudgetFailure]:
    """Return every committed suite-cost budget exceeded by ``record``.

    Wall-clock metrics (``causes.*`` ``limit``, ``total_file_wall_seconds``,
    ``idle_seconds``, ``collection_seconds``) default to advisory severity:
    they move with host contention alone, so they are reported but never
    fail the gate. CPU seconds, invocation counts, and RSS default to hard
    severity: those are contention-stable, so an overage is a real signal.
    An explicit ``enforce`` / ``cpu_enforce`` / ``count_enforce`` key on a
    budget entry overrides the family default for that dimension.
    """

    tolerance = _budget_tolerance(budgets, ci=ci)
    cpu_tolerance = _cpu_tolerance(budgets)
    failures: list[CostBudgetFailure] = []

    summary_budgets = budgets.get("summary")
    if isinstance(summary_budgets, Mapping):
        for metric, raw_budget in sorted(summary_budgets.items()):
            limit = _budget_dimension(raw_budget, "limit")
            actual = _summary_value(record, str(metric))
            if limit is None or actual is None:
                continue
            label = str(metric)
            if isinstance(raw_budget, Mapping) and raw_budget.get("per_worker"):
                actual = actual / worker_divisor(record)
                label = f"{metric} (per worker)"
            metric_tolerance = (
                cpu_tolerance if metric in _CPU_SUMMARY_METRICS else tolerance
            )
            severity = _resolve_severity(
                raw_budget, "enforce", _summary_default_severity(str(metric))
            )
            failure = CostBudgetFailure(
                label, actual, limit, metric_tolerance, severity
            )
            if actual > failure.allowed:
                failures.append(failure)

    cause_budgets = budgets.get("causes")
    if isinstance(cause_budgets, Mapping):
        for cause, raw_budget in sorted(cause_budgets.items()):
            wall_limit = _budget_dimension(raw_budget, "limit")
            if wall_limit is not None:
                actual_wall = _cause_seconds(record, str(cause)) or 0.0
                severity = _resolve_severity(raw_budget, "enforce", "advisory")
                failure = CostBudgetFailure(
                    f"causes.{cause}", actual_wall, wall_limit, tolerance, severity
                )
                if actual_wall > failure.allowed:
                    failures.append(failure)

            cpu_limit = _budget_dimension(raw_budget, "cpu_limit")
            if cpu_limit is not None:
                actual_cpu = _cause_cpu_seconds(record, str(cause)) or 0.0
                severity = _resolve_severity(raw_budget, "cpu_enforce", "hard")
                failure = CostBudgetFailure(
                    f"causes.{cause}.cpu",
                    actual_cpu,
                    cpu_limit,
                    cpu_tolerance,
                    severity,
                )
                if actual_cpu > failure.allowed:
                    failures.append(failure)

            count_limit = _budget_dimension(raw_budget, "count_limit")
            if count_limit is not None:
                actual_count = float(_cause_count(record, str(cause)) or 0)
                severity = _resolve_severity(raw_budget, "count_enforce", "hard")
                failure = CostBudgetFailure(
                    f"causes.{cause}.count", actual_count, count_limit, 0.0, severity
                )
                if actual_count > failure.allowed:
                    failures.append(failure)

    return failures


def format_cost_budget_failure(
    record: Mapping[str, Any], failure: CostBudgetFailure
) -> str:
    """Render one failure, annotated with its sibling CPU/count figures.

    A wall-clock advisory alone cannot tell a reader whether the host was
    busy or the suite regressed; the sibling figures for the same cause or
    summary metric let them judge that at a glance.
    """

    detail = _sibling_detail(record, failure)
    base = failure.format()
    return base if detail is None else f"{base} ({detail})"


def _sibling_detail(
    record: Mapping[str, Any], failure: CostBudgetFailure
) -> str | None:
    metric = failure.metric
    if metric.startswith("causes.") and not (
        metric.endswith(".cpu") or metric.endswith(".count")
    ):
        cause = metric[len("causes.") :]
        cpu = _cause_cpu_seconds(record, cause)
        count = _cause_count(record, cause)
        cpu_text = "n/a" if cpu is None else f"{cpu:.3f}s"
        count_text = "n/a" if count is None else str(count)
        return f"cpu={cpu_text}, count={count_text}"
    bare = metric.removesuffix(" (per worker)")
    cpu_metric = _WALL_TO_CPU_SUMMARY.get(bare)
    if cpu_metric is None:
        return None
    cpu = _summary_value(record, cpu_metric)
    return None if cpu is None else f"cpu={cpu:.3f}s"
