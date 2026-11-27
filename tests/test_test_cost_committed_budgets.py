"""Tests for committed suite cost budgets and budget-tool behavior."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests._test_cost import (
    build_cost_record,
    check_cost_budgets,
    load_cost_budgets,
    load_cost_record,
    write_cost_record,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_TOOL_PATH = REPO_ROOT / "tools" / "check_test_cost_budgets"
COMMITTED_BUDGETS_PATH = (
    REPO_ROOT / "tests" / "perf" / "baselines" / "test_cost_budgets.json"
)
BASELINE_RECORDING_PATH = (
    REPO_ROOT / "tests" / "perf" / "baselines" / "test_cost_baseline.json"
)


def _fresh_full_sample_record() -> dict[str, Any]:
    """Keep a compact fixture from the retained 2026-11-27 full recording.

    Source: ``file:explicit:f2f774fd30fcf4bccf90defa`` (63,815 nodes, four workers).
    The real 4.3 MB recording stays an artifact; only budget-relevant summary
    values are copied here so the real CLI has a small, deterministic input.
    """

    return {
        "schema": 1,
        "mode": "cost",
        "recorded_at": "2026-11-27T18:14:43.516479+00:00",
        "host": "athena",
        "worker_count": 4,
        "summary": {
            "total_file_wall_seconds": 10766.840657,
            "total_file_cpu_seconds": 7205.321394,
            "idle_seconds": 3561.519263,
            "peak_worker_rss_kib": 4193576,
            "collection_seconds": 192.311539,
            "collection_cpu_seconds": 173.474945,
            "causes": {
                "ace_page_enter": {
                    "count": 1155,
                    "seconds": 2119.765803,
                    "cpu_seconds": 2127.907329,
                },
                "ace_settle_pilot": {
                    "count": 18562,
                    "seconds": 1399.899501,
                    "cpu_seconds": 1398.292843,
                },
                "parser_create": {
                    "count": 2689,
                    "seconds": 156.256525,
                    "cpu_seconds": 155.742373,
                },
                "pilot_pause_delay": {
                    "count": 37599,
                    "seconds": 1213.662787,
                    "cpu_seconds": 1164.828661,
                },
                "subprocess_run": {
                    "count": 114809,
                    "seconds": 996.020707,
                    "cpu_seconds": 261.406694,
                },
                "textual_app_run_test_enter": {
                    "count": 5714,
                    "seconds": 1587.494618,
                    "cpu_seconds": 1592.339329,
                },
                "yaml_load": {
                    "count": 133913,
                    "seconds": 58.524307,
                    "cpu_seconds": 58.426651,
                },
            },
        },
    }


def _run_budget_cli(
    tmp_path: Path, record: dict[str, Any], *, ci: bool = False
) -> subprocess.CompletedProcess[str]:
    recording_path = tmp_path / "recording.json"
    recording_path.write_text(json.dumps(record), encoding="utf-8")
    env = os.environ.copy()
    env["GITHUB_ACTIONS"] = "true" if ci else "false"
    command = [
        sys.executable,
        str(CHECK_TOOL_PATH),
        "--recording",
        str(recording_path),
        "--budgets",
        str(COMMITTED_BUDGETS_PATH),
    ]
    if ci:
        command.append("--ci")
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _load_check_tool() -> ModuleType:
    loader = SourceFileLoader("check_test_cost_budgets_tool", str(CHECK_TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "check_test_cost_budgets_tool", CHECK_TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_wall_only_overage_case(tmp_path: Path) -> tuple[Path, Path]:
    """Build the reported bug as a fixture: a wall overage with CPU/count OK.

    Uses the real numbers from the 2026-08-23 `ace_page_enter` regression
    report (actual 680.949 with count 672) so this is a direct regression
    test for the reported bug, not a synthetic stand-in.
    """

    record = build_cost_record(
        [
            {
                "worker_id": "gw0",
                "wall_seconds": 700.0,
                "cpu_seconds": 700.0,
                "collection_seconds": 1.0,
                "peak_rss_kib": 100,
                "causes": {
                    "ace_page_enter": {
                        "count": 672,
                        "seconds": 680.949,
                        "cpu_seconds": 600.0,
                    }
                },
                "files": {},
            }
        ],
        mode="cost",
        worker_count=1,
        host="host",
        now=datetime(2026, 8, 23, tzinfo=UTC),
    )
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.15, "ci": 0.2, "cpu": 0.25},
        "summary": {},
        "causes": {
            "ace_page_enter": {
                "limit": 540.0,
                "enforce": "advisory",
                "cpu_limit": 700.0,
                "cpu_enforce": "hard",
                "count_limit": 840,
                "count_enforce": "hard",
            }
        },
    }

    recording_path = tmp_path / "recording.json"
    recording_path.write_text(json.dumps(record), encoding="utf-8")
    budget_path = tmp_path / "budgets.json"
    budget_path.write_text(json.dumps(budgets), encoding="utf-8")
    return recording_path, budget_path


def test_wall_only_overage_produces_advisories_and_exits_zero(tmp_path: Path) -> None:
    recording_path, budget_path = _write_wall_only_overage_case(tmp_path)
    record = load_cost_record(recording_path)
    budgets = load_cost_budgets(budget_path)

    failures = check_cost_budgets(record, budgets)

    assert [failure.metric for failure in failures] == ["causes.ace_page_enter"]
    assert failures[0].severity == "advisory"

    tool = _load_check_tool()
    exit_code = tool.main(
        ["--recording", str(recording_path), "--budgets", str(budget_path)]
    )

    assert exit_code == 0


def test_wall_only_overage_is_fatal_with_strict(tmp_path: Path) -> None:
    recording_path, budget_path = _write_wall_only_overage_case(tmp_path)

    tool = _load_check_tool()
    exit_code = tool.main(
        [
            "--recording",
            str(recording_path),
            "--budgets",
            str(budget_path),
            "--strict",
        ]
    )

    assert exit_code == 1


def test_committed_cost_budgets_are_valid() -> None:
    budgets = load_cost_budgets(COMMITTED_BUDGETS_PATH)

    assert budgets["summary"]["collection_seconds"]["limit"] == 60.0
    assert budgets["summary"]["collection_seconds"]["per_worker"] is True


def test_real_cli_accepts_compact_fixture_from_fresh_full_sample(
    tmp_path: Path,
) -> None:
    record = _fresh_full_sample_record()

    local = _run_budget_cli(tmp_path, record)
    ci = _run_budget_cli(tmp_path, record, ci=True)

    assert local.returncode == 0, local.stdout + local.stderr
    assert ci.returncode == 0, ci.stdout + ci.stderr


@pytest.mark.parametrize(
    ("metric", "ci_mode", "expected_failure"),
    [
        ("cpu", False, "total_file_cpu_seconds"),
        ("count", True, "causes.subprocess_run.count"),
        ("rss", True, "peak_worker_rss_kib"),
    ],
)
def test_real_cli_rejects_doctored_hard_budget_overages(
    tmp_path: Path, metric: str, ci_mode: bool, expected_failure: str
) -> None:
    record = _fresh_full_sample_record()
    budgets = load_cost_budgets(COMMITTED_BUDGETS_PATH)
    summary = record["summary"]

    if metric == "cpu":
        limit = float(budgets["summary"]["total_file_cpu_seconds"]["limit"])
        tolerance = float(budgets["tolerance"]["cpu"])
        summary["total_file_cpu_seconds"] = limit * (1.0 + tolerance) + 1.0
    elif metric == "count":
        count_limit = int(budgets["causes"]["subprocess_run"]["count_limit"])
        summary["causes"]["subprocess_run"]["count"] = count_limit + 1
    else:
        limit = float(budgets["summary"]["peak_worker_rss_kib"]["limit"])
        tolerance = float(budgets["tolerance"]["ci"])
        summary["peak_worker_rss_kib"] = int(limit * (1.0 + tolerance)) + 1

    result = _run_budget_cli(tmp_path, record, ci=ci_mode)

    assert result.returncode == 1, result.stdout + result.stderr
    assert expected_failure in result.stderr


_COMMITTED_BUDGETS: dict[str, Any] = load_cost_budgets(COMMITTED_BUDGETS_PATH)


_DEFAULT_SUMMARY_SEVERITY_FAMILIES = {
    "total_file_cpu_seconds": "hard",
    "collection_cpu_seconds": "hard",
    "peak_worker_rss_kib": "hard",
    "median_worker_rss_kib": "hard",
    "post_collection_worker_rss_kib": "hard",
}


def _committed_regression_cases() -> list[Any]:
    cases = []
    for metric, raw in sorted(_COMMITTED_BUDGETS["summary"].items()):
        limit = float(raw["limit"])
        per_worker = bool(raw.get("per_worker"))
        severity = raw.get(
            "enforce", _DEFAULT_SUMMARY_SEVERITY_FAMILIES.get(metric, "advisory")
        )
        cases.append(
            pytest.param(
                "summary",
                metric,
                "wall",
                limit,
                per_worker,
                severity,
                id=f"summary-{metric}",
            )
        )
    for cause, raw in sorted((_COMMITTED_BUDGETS.get("causes") or {}).items()):
        if "limit" in raw:
            cases.append(
                pytest.param(
                    "causes",
                    cause,
                    "wall",
                    float(raw["limit"]),
                    False,
                    raw.get("enforce", "advisory"),
                    id=f"causes-{cause}",
                )
            )
        if "cpu_limit" in raw:
            cases.append(
                pytest.param(
                    "causes",
                    cause,
                    "cpu",
                    float(raw["cpu_limit"]),
                    False,
                    raw.get("cpu_enforce", "hard"),
                    id=f"causes-{cause}-cpu",
                )
            )
        if "count_limit" in raw:
            cases.append(
                pytest.param(
                    "causes",
                    cause,
                    "count",
                    float(raw["count_limit"]),
                    False,
                    raw.get("count_enforce", "hard"),
                    id=f"causes-{cause}-count",
                )
            )
    return cases


@pytest.mark.parametrize(
    "scope, key, dimension, limit, per_worker, severity", _committed_regression_cases()
)
def test_every_committed_budget_flags_a_doubled_metric(
    scope: str, key: str, dimension: str, limit: float, per_worker: bool, severity: str
) -> None:
    """A record at 2x any committed limit must fail exactly that budget.

    This makes an accidentally-vacuous budget (typo'd metric name, unreachable
    cause key) a test failure instead of a silent no-op gate.
    """

    worker_count = 4
    if scope == "summary":
        actual = limit * 2 * (worker_count if per_worker else 1)
        record: dict[str, Any] = {
            "summary": {key: actual},
            "worker_count": worker_count,
        }
        expected_metric = f"{key} (per worker)" if per_worker else key
    else:
        cause_payload: dict[str, Any] = {"count": 1, "seconds": 0.0, "cpu_seconds": 0.0}
        if dimension == "wall":
            cause_payload["seconds"] = limit * 2
            expected_metric = f"causes.{key}"
        elif dimension == "cpu":
            cause_payload["cpu_seconds"] = limit * 2
            expected_metric = f"causes.{key}.cpu"
        else:
            cause_payload["count"] = int(limit * 2)
            expected_metric = f"causes.{key}.count"
        record = {"summary": {"causes": {key: cause_payload}}}

    failures = check_cost_budgets(record, _COMMITTED_BUDGETS)

    assert [failure.metric for failure in failures] == [expected_metric]
    assert failures[0].severity == severity


def test_committed_pre_epic_baseline_still_fails_recalibrated_budgets() -> None:
    """Keep the old measurement intact without pinning its former miss list."""

    baseline = load_cost_record(BASELINE_RECORDING_PATH)
    failures = check_cost_budgets(baseline, _COMMITTED_BUDGETS)

    assert baseline["summary"]["node_count"] == 27988
    assert all(failure.severity == "advisory" for failure in failures)
    assert any(failure.metric.startswith("causes.") for failure in failures)


def test_suggested_cpu_and_rss_limits_leave_fifteen_percent_headroom() -> None:
    tool = _load_check_tool()

    cpu_sample = 7205.321394
    cpu_limit = tool._suggest_limit([cpu_sample], 0.25, headroom=0.15)
    rss_sample = 4193576.0
    rss_limit = tool._suggest_limit([rss_sample], 0.15, headroom=0.15)

    assert cpu_limit == 6800.0
    assert rss_limit == 4300000.0
    assert cpu_sample <= cpu_limit * 1.25 * 0.85
    assert rss_sample <= rss_limit * 1.15 * 0.85


def test_suggest_output_round_trips_through_load_cost_budgets(tmp_path: Path) -> None:
    tool = _load_check_tool()
    write_cost_record(
        tmp_path,
        [
            {
                "worker_id": "gw0",
                "wall_seconds": 10.0,
                "cpu_seconds": 7.0,
                "collection_seconds": 1.25,
                "collection_cpu_seconds": 1.0,
                "peak_rss_kib": 500000,
                "causes": {
                    "parser_create": {"count": 2, "seconds": 0.5, "cpu_seconds": 0.3}
                },
                "files": {},
            }
        ],
        mode="cost",
        worker_count=1,
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    suggested = tool.suggest_budgets(tmp_path, None, {})

    out_path = tmp_path / "suggested_budgets.json"
    out_path.write_text(
        json.dumps(suggested, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    loaded = load_cost_budgets(out_path)

    assert loaded["schema"] == suggested["schema"] == 1
    assert loaded["summary"]["collection_seconds"]["per_worker"] is True
    assert loaded["summary"]["collection_seconds"]["enforce"] == "advisory"
    assert loaded["summary"]["collection_cpu_seconds"]["enforce"] == "hard"
    assert loaded["causes"]["parser_create"]["limit"] > 0
    assert loaded["causes"]["parser_create"]["enforce"] == "advisory"
    assert loaded["causes"]["parser_create"]["cpu_limit"] > 0
    assert loaded["causes"]["parser_create"]["cpu_enforce"] == "hard"
    assert loaded["causes"]["parser_create"]["count_limit"] > 0
    assert loaded["causes"]["parser_create"]["count_enforce"] == "hard"
