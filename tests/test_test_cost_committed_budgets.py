"""Tests for committed suite cost budgets and budget-tool behavior."""

from __future__ import annotations

import importlib.util
import json
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
    """The pre-epic baseline predates per-cause CPU attribution.

    Its two known-bad causes must still be reported (as advisories, since
    wall-only causes.* budgets are advisory by default) and must not trip any
    hard metric -- the recalibrated budgets add count_limit/cpu_limit
    dimensions this old recording cannot exercise.
    """

    baseline = load_cost_record(BASELINE_RECORDING_PATH)

    failures = check_cost_budgets(baseline, _COMMITTED_BUDGETS)

    assert [failure.metric for failure in failures] == [
        "causes.parser_create",
        "causes.yaml_load",
    ]
    assert [failure.severity for failure in failures] == ["advisory", "advisory"]


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
