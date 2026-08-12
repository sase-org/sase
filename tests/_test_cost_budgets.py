"""Budget loading and evaluation for suite-cost recordings."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from tests._test_cost_records import TEST_COST_SCHEMA, _cause_seconds, _summary_value


class CostBudgetFailure(NamedTuple):
    """One suite-cost metric that exceeded its committed budget."""

    metric: str
    actual: float
    limit: float
    tolerance: float

    @property
    def allowed(self) -> float:
        return self.limit * (1.0 + self.tolerance)

    def format(self) -> str:
        return (
            f"{self.metric}: actual {self.actual:.3f} exceeds budget "
            f"{self.limit:.3f} + {self.tolerance:.0%} tolerance "
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


def _budget_limit(raw_budget: object, *, ci: bool) -> float | None:
    raw_limit: Any = raw_budget
    if isinstance(raw_budget, Mapping):
        raw_limit = raw_budget.get("ci_limit") if ci else None
        if raw_limit is None:
            raw_limit = raw_budget.get("limit")
    try:
        return float(raw_limit)
    except (TypeError, ValueError):
        return None


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
    """Return every committed suite-cost budget exceeded by ``record``."""

    tolerance = _budget_tolerance(budgets, ci=ci)
    failures: list[CostBudgetFailure] = []
    summary_budgets = budgets.get("summary")
    if isinstance(summary_budgets, Mapping):
        for metric, raw_budget in sorted(summary_budgets.items()):
            limit = _budget_limit(raw_budget, ci=ci)
            actual = _summary_value(record, str(metric))
            if limit is None or actual is None:
                continue
            label = str(metric)
            if isinstance(raw_budget, Mapping) and raw_budget.get("per_worker"):
                actual = actual / worker_divisor(record)
                label = f"{metric} (per worker)"
            failure = CostBudgetFailure(label, actual, limit, tolerance)
            if actual > failure.allowed:
                failures.append(failure)

    cause_budgets = budgets.get("causes")
    if isinstance(cause_budgets, Mapping):
        for cause, raw_budget in sorted(cause_budgets.items()):
            limit = _budget_limit(raw_budget, ci=ci)
            if limit is None:
                continue
            actual = _cause_seconds(record, str(cause)) or 0.0
            failure = CostBudgetFailure(f"causes.{cause}", actual, limit, tolerance)
            if actual > failure.allowed:
                failures.append(failure)
    return failures
