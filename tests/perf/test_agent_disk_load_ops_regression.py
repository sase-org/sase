"""Unit tests for the agents disk-load operation-count regression checker."""

from __future__ import annotations

import json

from tests.perf.check_agent_disk_load_ops_regression import (
    DEFAULT_BASELINE_PATH,
    DEFAULT_REPORT_PATH,
    REPO_ROOT,
    check_agent_disk_load_ops,
    run_regression_check,
)


def test_default_paths_live_in_expected_locations() -> None:
    perf_dir = REPO_ROOT / "tests" / "perf"
    report_dir = REPO_ROOT / "sdd" / "plans" / "202608" / "perf_artifacts"

    assert DEFAULT_BASELINE_PATH == (
        perf_dir / "baselines" / "agent_disk_load_ops_baseline.json"
    )
    assert DEFAULT_REPORT_PATH == (
        report_dir / "agent_disk_load_ops_regression_check.json"
    )


def test_check_agent_disk_load_ops_passes_at_baseline() -> None:
    baseline = json.loads(DEFAULT_BASELINE_PATH.read_text(encoding="utf-8"))

    results = check_agent_disk_load_ops(current=baseline, baseline=baseline)

    assert all(result.passed for result in results)


def test_check_agent_disk_load_ops_fails_for_sync_reconcile_regression() -> None:
    baseline = json.loads(DEFAULT_BASELINE_PATH.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(baseline))
    current["scenarios"]["monitors_250"]["sync_reconcile_calls"] = 1
    current["scenarios"]["monitors_250"]["proc_store_reads"] = 1
    current["scenarios"]["monitors_250"]["artifact_index_queries"] = 2
    current["scenarios"]["monitors_250"]["monitor_reconcile_index_queries"] = 1

    results = check_agent_disk_load_ops(current=current, baseline=baseline)

    assert not all(result.passed for result in results)
    assert any(
        result.metric == "sync_reconcile_calls" and not result.passed
        for result in results
    )
    assert any(
        result.metric == "proc_store_reads_scales_with_monitor_count"
        and not result.passed
        for result in results
    )


def test_current_disk_load_operation_counts_match_baseline() -> None:
    report = run_regression_check()

    assert report["passed"] is True
