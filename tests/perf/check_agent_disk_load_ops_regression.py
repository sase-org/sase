"""Regression checker for Agents-tab disk-load operation counts."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.perf.bench_agent_disk_load_ops import run_benchmark  # noqa: E402

DEFAULT_BASELINE_PATH = (
    REPO_ROOT / "tests" / "perf" / "baselines" / "agent_disk_load_ops_baseline.json"
)
DEFAULT_REPORT_PATH = (
    REPO_ROOT
    / "sdd"
    / "plans"
    / "202608"
    / "perf_artifacts"
    / "agent_disk_load_ops_regression_check.json"
)


@dataclass(frozen=True)
class GateResult:
    """Per-scenario operation-count result."""

    scenario: str
    metric: str
    current_value: int | None
    max_value: int | None
    failures: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "metric": self.metric,
            "current_value": self.current_value,
            "max_value": self.max_value,
            "passed": self.passed,
            "failures": list(self.failures),
        }


def check_agent_disk_load_ops(
    *,
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> list[GateResult]:
    """Compare operation counts against the committed baseline budgets."""

    results: list[GateResult] = []
    current_scenarios = current.get("scenarios")
    baseline_scenarios = baseline.get("scenarios")
    if not isinstance(current_scenarios, dict):
        return [
            GateResult(
                scenario="<payload>",
                metric="scenarios",
                current_value=None,
                max_value=None,
                failures=("current scenarios unavailable",),
            )
        ]
    if not isinstance(baseline_scenarios, dict):
        return [
            GateResult(
                scenario="<payload>",
                metric="scenarios",
                current_value=None,
                max_value=None,
                failures=("baseline scenarios unavailable",),
            )
        ]

    for scenario, budgets in baseline_scenarios.items():
        current_counts = current_scenarios.get(scenario)
        if not isinstance(current_counts, dict):
            results.append(
                GateResult(
                    scenario=scenario,
                    metric="<scenario>",
                    current_value=None,
                    max_value=None,
                    failures=("current scenario unavailable",),
                )
            )
            continue
        if not isinstance(budgets, dict):
            continue
        for metric, max_value in budgets.items():
            result = _check_metric(
                scenario=scenario,
                metric=metric,
                current_counts=current_counts,
                max_value=max_value,
            )
            results.append(result)
    results.extend(_check_scaling(current_scenarios, baseline_scenarios))
    return results


def _check_metric(
    *,
    scenario: str,
    metric: str,
    current_counts: dict[str, Any],
    max_value: object,
) -> GateResult:
    failures: list[str] = []
    current_raw = current_counts.get(metric)
    current_value = int(current_raw) if isinstance(current_raw, int) else None
    budget = int(max_value) if isinstance(max_value, int) else None
    if current_value is None:
        failures.append("current metric unavailable")
    if budget is None:
        failures.append("baseline budget unavailable")
    elif current_value is not None and current_value > budget:
        failures.append(f"current {current_value} exceeds budget {budget}")
    return GateResult(
        scenario=scenario,
        metric=metric,
        current_value=current_value,
        max_value=budget,
        failures=tuple(failures),
    )


def _check_scaling(
    current_scenarios: dict[str, Any],
    baseline_scenarios: dict[str, Any],
) -> list[GateResult]:
    """Assert the operation counts do not grow with synthetic monitor count."""

    scenario_names = list(baseline_scenarios)
    if len(scenario_names) < 2:
        return []
    first = current_scenarios.get(scenario_names[0])
    last = current_scenarios.get(scenario_names[-1])
    if not isinstance(first, dict) or not isinstance(last, dict):
        return []

    results: list[GateResult] = []
    for metric in (
        "proc_store_reads",
        "artifact_index_queries",
        "loader_index_queries",
        "monitor_reconcile_index_queries",
        "sync_reconcile_calls",
    ):
        first_value = first.get(metric)
        last_value = last.get(metric)
        failures: list[str] = []
        if not isinstance(first_value, int) or not isinstance(last_value, int):
            failures.append("scaling metric unavailable")
            current_value = None
        else:
            current_value = last_value
            if last_value != first_value:
                failures.append(
                    f"count changed from {first_value} to {last_value} "
                    "as monitor rows increased"
                )
        results.append(
            GateResult(
                scenario=f"{scenario_names[0]}..{scenario_names[-1]}",
                metric=f"{metric}_scales_with_monitor_count",
                current_value=current_value,
                max_value=first_value if isinstance(first_value, int) else None,
                failures=tuple(failures),
            )
        )
    return results


def run_regression_check(
    *,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    monitor_counts: tuple[int, ...] = (0, 250),
) -> dict[str, Any]:
    """Run the current benchmark and return a JSON-serializable report."""

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = run_benchmark(monitor_counts=monitor_counts)
    results = check_agent_disk_load_ops(current=current, baseline=baseline)
    passed = all(result.passed for result in results)
    return {
        "schema_version": 1,
        "baseline_path": str(baseline_path),
        "passed": passed,
        "results": [result.as_dict() for result in results],
        "current": current,
        "baseline": baseline,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument(
        "--monitor-counts",
        type=int,
        nargs="+",
        default=[0, 250],
        help="Synthetic monitor row counts to run.",
    )
    args = parser.parse_args(argv)

    report = run_regression_check(
        baseline_path=args.baseline,
        monitor_counts=tuple(args.monitor_counts),
    )
    text = json.dumps(report, indent=2, sort_keys=True)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
