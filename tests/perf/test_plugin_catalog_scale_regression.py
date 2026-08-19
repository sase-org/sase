"""Unit tests for the plugin-catalog scale regression checker."""

from __future__ import annotations

import json
from typing import Any

from tests.perf.check_plugin_catalog_scale_regression import (
    DEFAULT_BASELINE_PATH,
    DEFAULT_REPORT_PATH,
    REPO_ROOT,
    check_plugin_catalog_scale,
    run_regression_check,
)
from tests.perf.plugin_catalog_scale import (
    GITHUB_SEARCH_CAP_ENTRIES,
    INSTALLED_SCALE_COUNT,
    TARGET_P95_MS,
    expected_enrich_ops,
    load_baseline,
)


def _tui_row(*, filter_p95: float = 11.0, j_p95: float = 0.5) -> dict[str, Any]:
    return {
        "filter_keystroke": {"p95_ms": filter_p95},
        "j_press": {"p95_ms": j_p95},
    }


def _payload(
    *,
    enrich_1000: dict[str, float] | None = None,
    enrich_2000: dict[str, float] | None = None,
    fetch_2000: dict[str, float] | None = None,
    truncation: dict[str, float] | None = None,
    tui_2000: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "enrich": {
            "1000": enrich_1000 or expected_enrich_ops(1000),
            "2000": enrich_2000 or expected_enrich_ops(2000),
        },
        "fetch": {"2000": fetch_2000 or {"returned_entries": 2000.0}},
        "truncation": truncation
        or {
            "returned_entries": float(GITHUB_SEARCH_CAP_ENTRIES),
            "truncated": 1.0,
            "has_truncation_warning": 1.0,
        },
        "tui": {"2000": tui_2000 or _tui_row()},
    }


def test_default_paths_live_in_expected_locations() -> None:
    perf_dir = REPO_ROOT / "tests" / "perf"
    report_dir = REPO_ROOT / "sdd" / "plans" / "202608" / "perf_artifacts"

    assert DEFAULT_BASELINE_PATH == (
        perf_dir / "baselines" / "plugin_catalog_scale_baseline.json"
    )
    assert DEFAULT_REPORT_PATH == (
        report_dir / "plugin_catalog_scale_regression_check.json"
    )


def test_check_passes_at_committed_baseline_with_live_op_counts() -> None:
    baseline = load_baseline()
    current = _payload(tui_2000=baseline["tui"]["2000"])

    results = check_plugin_catalog_scale(current=current, baseline=baseline)

    assert all(result.passed for result in results)


def test_check_fails_when_filter_p95_returns_to_pre_fix_budget() -> None:
    baseline = load_baseline()
    current = _payload(tui_2000=_tui_row(filter_p95=46.7))

    results = check_plugin_catalog_scale(current=current, baseline=baseline)

    failed = [result for result in results if not result.passed]
    assert failed
    assert any("filter_keystroke" in result.metric for result in failed)
    assert any("exceeds ceiling" in result.failures[0] for result in failed)
    assert TARGET_P95_MS == 16.0


def test_check_fails_when_eager_fetches_scale_with_catalog() -> None:
    baseline = load_baseline()
    current = _payload(
        enrich_2000={
            "fetch_calls": 2000.0,
            "scan_work": 0.0,
            "installed_lookups": 0.0,
        }
    )

    results = check_plugin_catalog_scale(current=current, baseline=baseline)

    failed = [result for result in results if not result.passed]
    assert any(result.metric == "enrich.2000.fetch_calls" for result in failed)


def test_check_fails_when_truncation_is_silent() -> None:
    baseline = load_baseline()
    current = _payload(
        truncation={
            "returned_entries": float(GITHUB_SEARCH_CAP_ENTRIES),
            "truncated": 0.0,
            "has_truncation_warning": 0.0,
        }
    )

    results = check_plugin_catalog_scale(current=current, baseline=baseline)

    failed_metrics = {result.metric for result in results if not result.passed}
    assert "truncation.truncated" in failed_metrics
    assert "truncation.has_truncation_warning" in failed_metrics


def test_current_operation_counts_match_enforced_budgets() -> None:
    report = run_regression_check()

    assert report["passed"] is True
    assert report["current"]["enrich"]["2000"]["fetch_calls"] == float(
        INSTALLED_SCALE_COUNT
    )
    assert json.loads(json.dumps(report["results"]))
