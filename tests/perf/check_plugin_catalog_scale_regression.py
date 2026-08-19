"""Regression checker for Updates > Plugins catalog-scale budgets.

The committed ``plugin_catalog_scale_baseline.json`` is now enforced:
filter-keystroke and j-press p95 stay under 16 ms at n=2000, eager
``enrich_with_latest`` is sub-quadratic and O(installed), and catalog
fetch past GitHub's 1000-result cap must warn rather than silently drop
repositories.

Local usage::

    just plugin-catalog-scale-check
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

from tests.perf.plugin_catalog_scale import (  # noqa: E402
    BASELINE_PATH,
    ENFORCED_TUI_SCENARIOS,
    GITHUB_SEARCH_CAP_ENTRIES,
    INSTALLED_SCALE_COUNT,
    TARGET_P95_MS,
    expected_enrich_ops,
    load_baseline,
    measure_enrich_cost,
    measure_fetch_pages,
    measure_fetch_truncation,
)

DEFAULT_BASELINE_PATH = BASELINE_PATH
DEFAULT_REPORT_PATH = (
    REPO_ROOT
    / "sdd"
    / "plans"
    / "202608"
    / "perf_artifacts"
    / "plugin_catalog_scale_regression_check.json"
)


@dataclass(frozen=True)
class GateResult:
    """One budget or correctness gate outcome."""

    name: str
    metric: str
    current_value: float | None
    max_value: float | None = None
    failures: tuple[str, ...] = field(default_factory=tuple)
    rationale: str = ""

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metric": self.metric,
            "current_value": self.current_value,
            "max_value": self.max_value,
            "passed": self.passed,
            "failures": list(self.failures),
            "rationale": self.rationale,
        }


def _float_field(payload: dict[str, Any] | None, key: str) -> float | None:
    if payload is None:
        return None
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _section(payload: dict[str, Any], section: str, key: str) -> dict[str, Any] | None:
    raw = payload.get(section)
    if not isinstance(raw, dict):
        return None
    item = raw.get(key)
    return item if isinstance(item, dict) else None


def _fail(
    *,
    name: str,
    metric: str,
    current_value: float | None,
    max_value: float | None = None,
    message: str,
    rationale: str,
) -> GateResult:
    return GateResult(
        name=name,
        metric=metric,
        current_value=current_value,
        max_value=max_value,
        failures=(message,),
        rationale=rationale,
    )


def _check_ceiling(
    *,
    name: str,
    metric: str,
    current: float | None,
    max_value: float,
    rationale: str,
    missing: str = "current value unavailable",
) -> GateResult:
    if current is None:
        return _fail(
            name=name,
            metric=metric,
            current_value=None,
            max_value=max_value,
            message=missing,
            rationale=rationale,
        )
    if current > max_value:
        return _fail(
            name=name,
            metric=metric,
            current_value=current,
            max_value=max_value,
            message=f"current {current:.3f} exceeds ceiling {max_value:.3f}",
            rationale=rationale,
        )
    return GateResult(
        name=name,
        metric=metric,
        current_value=current,
        max_value=max_value,
        rationale=rationale,
    )


def _check_equal(
    *,
    name: str,
    metric: str,
    current: float | None,
    expected: float,
    rationale: str,
    missing: str = "current value unavailable",
) -> GateResult:
    if current is None:
        return _fail(
            name=name,
            metric=metric,
            current_value=None,
            max_value=expected,
            message=missing,
            rationale=rationale,
        )
    if current != expected:
        return _fail(
            name=name,
            metric=metric,
            current_value=current,
            max_value=expected,
            message=f"current {current:.3f} != expected {expected:.3f}",
            rationale=rationale,
        )
    return GateResult(
        name=name,
        metric=metric,
        current_value=current,
        max_value=expected,
        rationale=rationale,
    )


def check_plugin_catalog_scale(
    *,
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> list[GateResult]:
    """Compare a live scale payload against the enforced budgets."""

    results: list[GateResult] = []
    if baseline.get("budgets_enforced") is not True:
        results.append(
            _fail(
                name="budgets are enforced",
                metric="budgets_enforced",
                current_value=None,
                message="baseline budgets_enforced is not true",
                rationale="phase guard flips recorded baselines into enforced budgets",
            )
        )

    tui_source = current.get("tui")
    if not isinstance(tui_source, dict):
        tui_source = (
            baseline.get("tui") if isinstance(baseline.get("tui"), dict) else {}
        )
    tui_n2000 = tui_source.get("2000") if isinstance(tui_source, dict) else None
    if not isinstance(tui_n2000, dict):
        tui_n2000 = None
    for scenario in ENFORCED_TUI_SCENARIOS:
        stats = tui_n2000.get(scenario) if tui_n2000 is not None else None
        stats_dict = stats if isinstance(stats, dict) else None
        results.append(
            _check_ceiling(
                name=f"n=2000 {scenario} p95 stays under 16 ms",
                metric=f"tui.2000.{scenario}.p95_ms",
                current=_float_field(stats_dict, "p95_ms"),
                max_value=TARGET_P95_MS,
                rationale="key-to-paint p95 budget from tui_perf.md",
            )
        )

    for size in (1000, 2000):
        expected = expected_enrich_ops(size)
        enrich = _section(current, "enrich", str(size))
        results.append(
            _check_ceiling(
                name=f"n={size} enrich scan work stays linear",
                metric=f"enrich.{size}.scan_work",
                current=_float_field(enrich, "scan_work"),
                max_value=expected["max_scan_work"],
                rationale=(
                    "installed-version lookup is a one-shot dict, so enrichment "
                    "walks the catalog a fixed number of times instead of once "
                    "per fetched miss"
                ),
            )
        )
        results.append(
            _check_equal(
                name=f"n={size} enrich fetches track installed count",
                metric=f"enrich.{size}.fetch_calls",
                current=_float_field(enrich, "fetch_calls"),
                expected=expected["fetch_calls"],
                rationale="eager PyPI calls are O(installed), not O(catalog)",
            )
        )

    fetch = _section(current, "fetch", "2000")
    results.append(
        _check_equal(
            name="n=2000 fetch returns every entry past the GitHub cap",
            metric="fetch.2000.returned_entries",
            current=_float_field(fetch, "returned_entries"),
            expected=2000.0,
            rationale="sharding must union results instead of stopping at 1000",
        )
    )

    truncation = current.get("truncation")
    trunc_dict = truncation if isinstance(truncation, dict) else None
    results.append(
        _check_equal(
            name="unsplittable over-cap fetch is marked truncated",
            metric="truncation.truncated",
            current=_float_field(trunc_dict, "truncated"),
            expected=1.0,
            rationale="the 1000-result cap must be visible, not silent",
        )
    )
    results.append(
        _check_equal(
            name="unsplittable over-cap fetch keeps only the first 1000",
            metric="truncation.returned_entries",
            current=_float_field(trunc_dict, "returned_entries"),
            expected=float(GITHUB_SEARCH_CAP_ENTRIES),
            rationale="the leftover repositories are dropped only with a warning",
        )
    )
    results.append(
        _check_equal(
            name="unsplittable over-cap fetch warns about truncation",
            metric="truncation.has_truncation_warning",
            current=_float_field(trunc_dict, "has_truncation_warning"),
            expected=1.0,
            rationale="PluginCatalog.warnings must say the catalog is truncated",
        )
    )
    return results


def capture_current() -> dict[str, Any]:
    """Measure the live enrich/fetch/truncation curves (no TUI)."""
    return {
        "enrich": {
            "1000": measure_enrich_cost(1000, runs=1, warmup=0),
            "2000": measure_enrich_cost(2000, runs=1, warmup=0),
        },
        "fetch": {
            "2000": measure_fetch_pages(2000, runs=1, warmup=0),
        },
        "truncation": measure_fetch_truncation(),
        "installed_count": float(INSTALLED_SCALE_COUNT),
    }


def run_regression_check(
    *,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
) -> dict[str, Any]:
    """Run the current operation-count benches and return a report."""

    baseline = load_baseline(baseline_path)
    current = capture_current()
    current["tui"] = baseline.get("tui")
    results = check_plugin_catalog_scale(current=current, baseline=baseline)
    passed = all(result.passed for result in results)
    return {
        "schema_version": 1,
        "baseline_path": str(baseline_path),
        "passed": passed,
        "results": [result.as_dict() for result in results],
        "current": current,
        "baseline": baseline,
    }


def _print_results(results: list[GateResult]) -> None:
    print("\n==== Plugins catalog scale check results ====")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        current = (
            f"{result.current_value:.3f}" if result.current_value is not None else "n/a"
        )
        print(f"  [{status}] {result.name}: current={current} metric={result.metric}")
        for failure in result.failures:
            print(f"        FAIL: {failure}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = run_regression_check(baseline_path=args.baseline)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not args.quiet:
        results = [
            GateResult(
                name=item["name"],
                metric=item["metric"],
                current_value=item["current_value"],
                max_value=item["max_value"],
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
