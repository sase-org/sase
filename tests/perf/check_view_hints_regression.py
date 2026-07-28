"""Regression-floor checker for Agents-tab view-hints latency.

The committed ``view_hints_baseline.json`` captures the synchronous
pre-optimization keypath. This checker runs the current Pilot-driven scenario
set and fails if the traced spans drift back toward that baseline or if cached
repeat/refresh paths resume scanning the annotated document.

Local usage::

    just view-hints-perf-check
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.perf.tui_trace.view_hints import (  # noqa: E402
    VIEW_HINTS_BASELINE_PATH,
    VIEW_HINTS_BASELINE_RUNS,
    run_view_hints_baseline,
)

DEFAULT_BASELINE_PATH = VIEW_HINTS_BASELINE_PATH
DEFAULT_REPORT_PATH = (
    REPO_ROOT
    / "sdd"
    / "plans"
    / "202607"
    / "perf_artifacts"
    / "view_hints_regression_check.json"
)
DEFAULT_TRACE_PATH = Path.home() / ".sase" / "perf" / "view_hints_floor_trace.jsonl"
DEFAULT_PERF_PATH = Path.home() / ".sase" / "perf" / "view_hints_floor_jk.jsonl"


@dataclass(frozen=True)
class SpanGate:
    """One traced span threshold."""

    name: str
    step: str
    span: str
    stat: str = "p50_ms"
    max_ms: float | None = None
    max_baseline_ratio: float | None = None
    rationale: str = ""


@dataclass(frozen=True)
class CounterGate:
    """One hint-counter threshold."""

    name: str
    step: str
    counter: str
    max_value: float | None = None
    max_baseline_ratio: float | None = None
    missing_is_zero: bool = False
    rationale: str = ""


@dataclass(frozen=True)
class GateResult:
    """Per-gate outcome for the report."""

    name: str
    step: str
    metric: str
    current_value: float | None
    baseline_value: float | None = None
    max_value: float | None = None
    max_baseline_ratio: float | None = None
    failures: tuple[str, ...] = field(default_factory=tuple)
    rationale: str = ""

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "step": self.step,
            "metric": self.metric,
            "current_value": self.current_value,
            "baseline_value": self.baseline_value,
            "max_value": self.max_value,
            "max_baseline_ratio": self.max_baseline_ratio,
            "passed": self.passed,
            "failures": list(self.failures),
            "rationale": self.rationale,
        }


_DEFAULT_SPAN_GATES = (
    SpanGate(
        "large reply first press reaches the hint bar quickly",
        step="large_reply_first_press",
        span="agents.view_files",
        max_ms=20.0,
        max_baseline_ratio=0.70,
        rationale="keypress-to-bar span must stay well below the synchronous baseline",
    ),
    SpanGate(
        "large reply repeat press reaches the hint bar quickly",
        step="large_reply_repeat_press",
        span="agents.view_files",
        max_ms=20.0,
        max_baseline_ratio=0.70,
        rationale="warm repeat press must stay bounded by bar mount/scheduling cost",
    ),
    SpanGate(
        "unfolded family press reaches the hint bar quickly",
        step="family_container_unfolded_press",
        span="agents.view_files",
        max_ms=30.0,
        max_baseline_ratio=0.50,
        rationale="family size must not scale the keypress-to-bar path",
    ),
    SpanGate(
        "repeat press uses the cached hint render",
        step="large_reply_repeat_press",
        span="widget.prompt_panel.update_display_with_hints",
        max_ms=12.0,
        max_baseline_ratio=0.70,
        rationale="repeat v on the same row should reuse the annotated document cache",
    ),
    SpanGate(
        "auto-refresh current-document check stays cheap",
        step="hint_mode_auto_refresh",
        span="agents.view_hints_refresh",
        max_ms=18.0,
        max_baseline_ratio=0.80,
        rationale="unchanged refreshes should validate cache currency, not rebuild hints",
    ),
    SpanGate(
        "unfolded family render stays bounded",
        step="family_container_unfolded_press",
        span="widget.prompt_panel.update_display_with_hints",
        max_ms=65.0,
        max_baseline_ratio=0.80,
        rationale="the family render may run off-pump, but capped input keeps it bounded",
    ),
)

_DEFAULT_COUNTER_GATES = (
    CounterGate(
        "repeat press does not rescan annotated text",
        step="large_reply_repeat_press",
        counter="annotated_chars",
        max_value=0.0,
        missing_is_zero=True,
        rationale="cache hits should publish existing mappings without regex scanning",
    ),
    CounterGate(
        "auto-refresh does not rebuild hints",
        step="hint_mode_auto_refresh",
        counter="annotated_chars",
        max_value=0.0,
        missing_is_zero=True,
        rationale="unchanged refreshes should not enter the hint scanner",
    ),
    CounterGate(
        "unfolded family hint scan is capped",
        step="family_container_unfolded_press",
        counter="annotated_chars",
        max_value=200_000.0,
        max_baseline_ratio=0.40,
        rationale="family members share a total hint scan budget",
    ),
)


def _median_step(payload: dict[str, Any], step: str) -> dict[str, Any] | None:
    median = payload.get("median")
    if not isinstance(median, dict):
        return None
    step_payload = median.get(step)
    return step_payload if isinstance(step_payload, dict) else None


def _span_value(
    payload: dict[str, Any],
    *,
    step: str,
    span: str,
    stat: str,
) -> float | None:
    step_payload = _median_step(payload, step)
    if step_payload is None:
        return None
    spans = step_payload.get("spans")
    if not isinstance(spans, dict):
        return None
    span_payload = spans.get(span)
    if not isinstance(span_payload, dict):
        return None
    value = span_payload.get(stat)
    return float(value) if value is not None else None


def _counter_value(
    payload: dict[str, Any],
    *,
    step: str,
    counter: str,
    missing_is_zero: bool,
) -> float | None:
    step_payload = _median_step(payload, step)
    if step_payload is None:
        return 0.0 if missing_is_zero else None
    counters = step_payload.get("hint_counters")
    if not isinstance(counters, dict):
        return 0.0 if missing_is_zero else None
    value = counters.get(counter)
    if value is None:
        return 0.0 if missing_is_zero else None
    return float(value)


def _check_thresholds(
    *,
    current: float | None,
    baseline: float | None,
    max_value: float | None,
    max_baseline_ratio: float | None,
    unit: str,
) -> list[str]:
    failures: list[str] = []
    if current is None:
        failures.append("current value unavailable")
        return failures
    if max_value is not None and current > max_value:
        failures.append(
            f"current {current:.3f}{unit} exceeds absolute ceiling "
            f"{max_value:.3f}{unit}"
        )
    if max_baseline_ratio is not None:
        if baseline is None:
            failures.append("baseline value unavailable")
        else:
            ceiling = baseline * max_baseline_ratio
            if current > ceiling:
                failures.append(
                    f"current {current:.3f}{unit} exceeds "
                    f"{max_baseline_ratio:.2f}x baseline ceiling "
                    f"{ceiling:.3f}{unit}"
                )
    return failures


def check_view_hints(
    *,
    current: dict[str, Any],
    baseline: dict[str, Any],
    span_gates: tuple[SpanGate, ...] = _DEFAULT_SPAN_GATES,
    counter_gates: tuple[CounterGate, ...] = _DEFAULT_COUNTER_GATES,
) -> list[GateResult]:
    """Compare a current view-hints run against the committed baseline."""

    results: list[GateResult] = []
    for gate in span_gates:
        current_value = _span_value(
            current,
            step=gate.step,
            span=gate.span,
            stat=gate.stat,
        )
        baseline_value = _span_value(
            baseline,
            step=gate.step,
            span=gate.span,
            stat=gate.stat,
        )
        failures = _check_thresholds(
            current=current_value,
            baseline=baseline_value,
            max_value=gate.max_ms,
            max_baseline_ratio=gate.max_baseline_ratio,
            unit=" ms",
        )
        results.append(
            GateResult(
                name=gate.name,
                step=gate.step,
                metric=f"{gate.span}.{gate.stat}",
                current_value=current_value,
                baseline_value=baseline_value,
                max_value=gate.max_ms,
                max_baseline_ratio=gate.max_baseline_ratio,
                failures=tuple(failures),
                rationale=gate.rationale,
            )
        )

    for gate in counter_gates:
        current_value = _counter_value(
            current,
            step=gate.step,
            counter=gate.counter,
            missing_is_zero=gate.missing_is_zero,
        )
        baseline_value = _counter_value(
            baseline,
            step=gate.step,
            counter=gate.counter,
            missing_is_zero=gate.missing_is_zero,
        )
        failures = _check_thresholds(
            current=current_value,
            baseline=baseline_value,
            max_value=gate.max_value,
            max_baseline_ratio=gate.max_baseline_ratio,
            unit="",
        )
        results.append(
            GateResult(
                name=gate.name,
                step=gate.step,
                metric=f"hint_counters.{gate.counter}",
                current_value=current_value,
                baseline_value=baseline_value,
                max_value=gate.max_value,
                max_baseline_ratio=gate.max_baseline_ratio,
                failures=tuple(failures),
                rationale=gate.rationale,
            )
        )
    return results


async def _capture_current(
    *,
    runs: int,
    trace_path: Path,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gp_file = root / "bench.sase"
        gp_file.write_text("", encoding="utf-8")
        return await run_view_hints_baseline(
            gp_file=gp_file,
            trace_path=trace_path,
            runs=runs,
        )


def run_regression_check(
    *,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    runs: int = VIEW_HINTS_BASELINE_RUNS,
    trace_path: Path = DEFAULT_TRACE_PATH,
    perf_path: Path = DEFAULT_PERF_PATH,
) -> dict[str, Any]:
    """Run the current benchmark and return a JSON-serializable report."""

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    perf_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["SASE_TUI_TRACE"] = "1"
    os.environ["SASE_TUI_TRACE_PATH"] = str(trace_path)
    os.environ["SASE_TUI_PERF"] = "1"
    os.environ["SASE_TUI_PERF_PATH"] = str(perf_path)

    current = asyncio.run(_capture_current(runs=runs, trace_path=trace_path))
    results = check_view_hints(current=current, baseline=baseline)
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


def _print_results(results: list[GateResult]) -> None:
    print("\n==== View-hints floor check results ====")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        baseline = (
            f"{result.baseline_value:.3f}"
            if result.baseline_value is not None
            else "n/a"
        )
        current = (
            f"{result.current_value:.3f}" if result.current_value is not None else "n/a"
        )
        print(
            f"  [{status}] {result.name}: current={current} "
            f"baseline={baseline} metric={result.metric}"
        )
        for failure in result.failures:
            print(f"        FAIL: {failure}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--runs", type=int, default=VIEW_HINTS_BASELINE_RUNS)
    parser.add_argument("--trace-path", type=Path, default=DEFAULT_TRACE_PATH)
    parser.add_argument("--perf-path", type=Path, default=DEFAULT_PERF_PATH)
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = run_regression_check(
        baseline_path=args.baseline,
        runs=args.runs,
        trace_path=args.trace_path,
        perf_path=args.perf_path,
    )
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not args.quiet:
        results = [
            GateResult(
                name=item["name"],
                step=item["step"],
                metric=item["metric"],
                current_value=item["current_value"],
                baseline_value=item["baseline_value"],
                max_value=item["max_value"],
                max_baseline_ratio=item["max_baseline_ratio"],
                failures=tuple(item["failures"]),
                rationale=item["rationale"],
            )
            for item in report["results"]
        ]
        _print_results(results)
        print(f"\nreport written to {args.report_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
