"""CI-friendly regression check for Rust-backed agent launch latency.

The Phase 1 launch benchmark captured the pre-migration parent-side cost,
including the one-second sleeps that used to serialize model/repeat fan-out.
This checker runs the current fake-spawn launch benchmark without those sleeps
and fails if the fan-out scenarios drift back toward the old baseline.

Local usage::

    just launch-perf-check
"""

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

from tests.perf.bench_agent_launch import run_benchmark  # noqa: E402

DEFAULT_BASELINE_PATH = (
    REPO_ROOT
    / "plans"
    / "202605"
    / "perf_artifacts"
    / "agent_launch_phase1_baseline.json"
)
DEFAULT_REPORT_PATH = (
    REPO_ROOT
    / "plans"
    / "202605"
    / "perf_artifacts"
    / "agent_launch_regression_check.json"
)


@dataclass(frozen=True)
class ScenarioGate:
    """One benchmark scenario threshold."""

    name: str
    max_median_ms: float | None = None
    max_baseline_ratio: float | None = None
    rationale: str = ""


@dataclass(frozen=True)
class ScenarioResult:
    """Per-scenario gate outcome."""

    gate: ScenarioGate
    current_median_ms: float | None
    baseline_median_ms: float | None
    failures: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.gate.name,
            "current_median_ms": self.current_median_ms,
            "baseline_median_ms": self.baseline_median_ms,
            "max_median_ms": self.gate.max_median_ms,
            "max_baseline_ratio": self.gate.max_baseline_ratio,
            "passed": self.passed,
            "failures": list(self.failures),
            "rationale": self.gate.rationale,
        }


_DEFAULT_GATES = (
    ScenarioGate(
        "model_fanout",
        max_baseline_ratio=0.25,
        rationale="model fan-out must stay far below the Phase 1 sleep baseline",
    ),
    ScenarioGate(
        "repeat_fanout",
        max_baseline_ratio=0.25,
        rationale="repeat fan-out must stay far below the Phase 1 sleep baseline",
    ),
    ScenarioGate(
        "plain_prompt",
        max_median_ms=100.0,
        rationale="single-prompt fake launch should stay comfortably CI-cheap",
    ),
    ScenarioGate(
        "vcs_prompt",
        max_median_ms=100.0,
        rationale="VCS preallocated fake launch should stay comfortably CI-cheap",
    ),
    ScenarioGate(
        "wait_deferred",
        max_median_ms=100.0,
        rationale="deferred-workspace fake launch should stay comfortably CI-cheap",
    ),
)


def _scenario_median_ms(payload: dict[str, Any], scenario: str) -> float | None:
    summary = (payload.get("scenarios") or {}).get(scenario)
    if not summary:
        return None
    value = summary.get("median_ms")
    return float(value) if value is not None else None


def check_scenarios(
    *,
    current: dict[str, Any],
    baseline: dict[str, Any],
    gates: tuple[ScenarioGate, ...] = _DEFAULT_GATES,
) -> list[ScenarioResult]:
    """Compare current benchmark output against the committed Phase 1 baseline."""

    results: list[ScenarioResult] = []
    for gate in gates:
        failures: list[str] = []
        current_median = _scenario_median_ms(current, gate.name)
        baseline_median = _scenario_median_ms(baseline, gate.name)
        if current_median is None:
            failures.append("current median unavailable")
        if gate.max_median_ms is not None and current_median is not None:
            if current_median > gate.max_median_ms:
                failures.append(
                    f"current median {current_median:.3f} ms exceeds "
                    f"absolute ceiling {gate.max_median_ms:.3f} ms"
                )
        if gate.max_baseline_ratio is not None:
            if baseline_median is None:
                failures.append("baseline median unavailable")
            elif current_median is not None:
                ceiling = baseline_median * gate.max_baseline_ratio
                if current_median > ceiling:
                    failures.append(
                        f"current median {current_median:.3f} ms exceeds "
                        f"{gate.max_baseline_ratio:.2f}x Phase 1 baseline "
                        f"ceiling {ceiling:.3f} ms"
                    )
        results.append(
            ScenarioResult(
                gate=gate,
                current_median_ms=current_median,
                baseline_median_ms=baseline_median,
                failures=tuple(failures),
            )
        )
    return results


def run_regression_check(
    *,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    runs: int = 3,
) -> dict[str, Any]:
    """Run the current benchmark and return a JSON-serializable report."""

    baseline = json.loads(baseline_path.read_text())
    current = run_benchmark(runs=runs, include_sleeps=False)
    results = check_scenarios(current=current, baseline=baseline)
    passed = all(result.passed for result in results)
    return {
        "schema_version": 1,
        "baseline_path": str(baseline_path),
        "runs": runs,
        "passed": passed,
        "results": [result.as_dict() for result in results],
        "current": current,
        "baseline": baseline,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)

    report = run_regression_check(baseline_path=args.baseline, runs=args.runs)
    text = json.dumps(report, indent=2, sort_keys=True)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
