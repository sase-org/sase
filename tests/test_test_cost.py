"""Unit tests for the opt-in suite cost-attribution harness."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests import _test_cost_plugin
from tests._test_cost import (
    build_cost_record,
    check_cost_budgets,
    cost_directory,
    format_cost_report,
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


class _FakePilotApp:
    is_running = True

    async def wait_for_refresh(self) -> bool:
        return True


class _FakePilot:
    app = _FakePilotApp()


async def _fake_pilot_pause(_pilot: _FakePilot, _delay: float | None) -> None:
    return None


def test_cost_directory_lives_under_the_timing_store(tmp_path: Path) -> None:
    assert cost_directory(tmp_path) == tmp_path / "timings" / "cost"


def test_build_cost_record_merges_workers_and_files() -> None:
    record = build_cost_record(
        [
            {
                "worker_id": "gw0",
                "wall_seconds": 10.0,
                "cpu_seconds": 7.0,
                "collection_seconds": 1.25,
                "peak_rss_kib": 500000,
                "rss_curve_kib": {
                    "start": 300000,
                    "post_collection": 400000,
                    "median": 450000,
                    "peak": 500000,
                    "sample_count": 4,
                },
                "causes": {"parser_create": {"count": 2, "seconds": 0.5}},
                "files": {
                    "tests/test_a.py": {
                        "node_count": 2,
                        "wall_seconds": 3.0,
                        "cpu_seconds": 2.0,
                        "causes": {"parser_create": {"count": 2, "seconds": 0.5}},
                    }
                },
            },
            {
                "worker_id": "gw1",
                "wall_seconds": 8.0,
                "cpu_seconds": 6.0,
                "collection_seconds": 1.0,
                "peak_rss_kib": 750000,
                "rss_curve_kib": {
                    "start": 350000,
                    "post_collection": 500000,
                    "median": 600000,
                    "peak": 750000,
                    "sample_count": 5,
                },
                "causes": {"yaml_load": {"count": 1, "seconds": 0.25}},
                "files": {
                    "tests/test_a.py": {
                        "node_count": 1,
                        "wall_seconds": 2.0,
                        "cpu_seconds": 1.0,
                        "causes": {"yaml_load": {"count": 1, "seconds": 0.25}},
                    }
                },
            },
        ],
        mode="cost",
        worker_count=2,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert record["summary"]["file_count"] == 1
    assert record["summary"]["node_count"] == 3
    assert record["summary"]["total_file_wall_seconds"] == 5.0
    assert record["summary"]["total_file_cpu_seconds"] == 3.0
    assert record["summary"]["idle_seconds"] == 2.0
    assert record["summary"]["collection_seconds"] == 2.25
    assert record["summary"]["peak_worker_rss_kib"] == 750000
    assert record["summary"]["worker_rss_curve_kib"] == {
        "start": 350000,
        "post_collection": 500000,
        "median": 475000,
        "peak": 750000,
        "sample_count": 9,
    }
    assert record["summary"]["causes"]["parser_create"] == {
        "count": 2,
        "seconds": 0.5,
    }
    assert record["files"]["tests/test_a.py"]["node_count"] == 3


def test_write_and_load_cost_record(tmp_path: Path) -> None:
    path = write_cost_record(
        tmp_path,
        [
            {
                "worker_id": "controller",
                "wall_seconds": 1.0,
                "cpu_seconds": 0.5,
                "collection_seconds": 0.25,
                "peak_rss_kib": 123,
                "causes": {},
                "files": {},
            }
        ],
        mode="cost",
        pid=12345,
        now=datetime(2026, 8, 9, 1, 2, 3, tzinfo=UTC),
    )

    assert path is not None
    assert path.name == "20260809T010203Z-12345.json"
    payload = load_cost_record(path)
    assert payload["schema"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["mode"] == "cost"


def test_format_cost_report_includes_diff_and_top_files() -> None:
    baseline = build_cost_record(
        [
            {
                "worker_id": "gw0",
                "wall_seconds": 1.0,
                "cpu_seconds": 1.0,
                "collection_seconds": 0.5,
                "peak_rss_kib": 100,
                "rss_curve_kib": {
                    "start": 80,
                    "post_collection": 90,
                    "median": 95,
                    "peak": 100,
                    "sample_count": 4,
                },
                "causes": {"parser_create": {"count": 1, "seconds": 1.0}},
                "files": {
                    "tests/test_a.py": {
                        "node_count": 1,
                        "wall_seconds": 2.0,
                        "cpu_seconds": 1.0,
                        "causes": {"parser_create": {"count": 1, "seconds": 1.0}},
                    }
                },
            }
        ],
        mode="baseline",
        worker_count=None,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    current = build_cost_record(
        [
            {
                "worker_id": "gw0",
                "wall_seconds": 1.0,
                "cpu_seconds": 1.0,
                "collection_seconds": 0.25,
                "peak_rss_kib": 100,
                "rss_curve_kib": {
                    "start": 70,
                    "post_collection": 80,
                    "median": 90,
                    "peak": 100,
                    "sample_count": 4,
                },
                "causes": {
                    "ace_settle_pilot": {"count": 2, "seconds": 0.25},
                    "parser_create": {"count": 1, "seconds": 0.5},
                },
                "files": {
                    "tests/test_a.py": {
                        "node_count": 1,
                        "wall_seconds": 1.0,
                        "cpu_seconds": 0.75,
                        "causes": {
                            "ace_settle_pilot": {"count": 2, "seconds": 0.25},
                            "parser_create": {"count": 1, "seconds": 0.5},
                        },
                    }
                },
            }
        ],
        mode="cost",
        worker_count=1,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    report = format_cost_report(current, baseline=baseline, top=1)

    assert "per-test wall: current 1.000s; baseline 2.000s" in report
    assert (
        "worker RSS curve: start=70 KiB, post_collection=80 KiB, "
        "median=85 KiB, peak=100 KiB, samples=4"
    ) in report
    assert "ACE settle_pilot: 0.250s (2x)" in report
    assert "sase.main.parser.create_parser: 0.500s (1x)" in report
    assert "by wall:" in report
    assert "tests/test_a.py" in report


def test_cost_budget_check_reports_regressions() -> None:
    record = build_cost_record(
        [
            {
                "worker_id": "gw0",
                "wall_seconds": 1.0,
                "cpu_seconds": 0.25,
                "collection_seconds": 2.0,
                "peak_rss_kib": 100,
                "causes": {"parser_create": {"count": 1, "seconds": 1.25}},
                "files": {
                    "tests/test_a.py": {
                        "node_count": 1,
                        "wall_seconds": 3.0,
                        "cpu_seconds": 1.0,
                        "causes": {"parser_create": {"count": 1, "seconds": 1.25}},
                    }
                },
            }
        ],
        mode="cost",
        worker_count=1,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.10},
        "summary": {"total_file_wall_seconds": {"limit": 2.0}},
        "causes": {"parser_create": {"limit": 1.0}},
    }

    failures = check_cost_budgets(record, budgets)

    assert [failure.metric for failure in failures] == [
        "total_file_wall_seconds",
        "causes.parser_create",
    ]
    assert failures[0].allowed == 2.2


def test_cost_budget_check_uses_wider_ci_tolerance() -> None:
    record = build_cost_record(
        [
            {
                "worker_id": "gw0",
                "wall_seconds": 1.0,
                "cpu_seconds": 1.0,
                "collection_seconds": 11.5,
                "peak_rss_kib": 100,
                "causes": {},
                "files": {},
            }
        ],
        mode="cost",
        worker_count=1,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.10, "ci": 0.20},
        "summary": {"collection_seconds": {"limit": 10.0}},
        "causes": {},
    }

    assert check_cost_budgets(record, budgets)
    assert check_cost_budgets(record, budgets, ci=True) == []


def test_committed_cost_budgets_are_valid() -> None:
    budgets = load_cost_budgets(Path("tests/perf/baselines/test_cost_budgets.json"))

    assert budgets["summary"]["collection_seconds"]["limit"] == 60.0
    assert budgets["summary"]["collection_seconds"]["per_worker"] is True


def test_cost_recorder_attributes_causes_to_current_file(tmp_path: Path) -> None:
    recorder = _test_cost_plugin.CostRecorder(tmp_path, mode="cost", worker_count=1)
    token = _test_cost_plugin._CURRENT_FILE.set("tests/test_a.py")
    try:
        with recorder.measure("parser_create"):
            pass
        recorder._record_item("tests/test_a.py", wall_seconds=1.0, cpu_seconds=0.25)
        payload = recorder._worker_payload()
    finally:
        _test_cost_plugin._CURRENT_FILE.reset(token)
        recorder._restore_patches()

    assert payload["files"]["tests/test_a.py"]["node_count"] == 1
    assert payload["files"]["tests/test_a.py"]["causes"]["parser_create"]["count"] == 1
    assert payload["causes"]["parser_create"]["count"] == 1
    assert payload["rss_curve_kib"]["sample_count"] >= 2
    assert payload["rss_curve_kib"]["peak"] >= payload["rss_curve_kib"]["start"]


async def test_cost_recorder_attributes_ace_settle_helpers(tmp_path: Path) -> None:
    recorder = _test_cost_plugin.CostRecorder(tmp_path, mode="cost", worker_count=1)
    token = _test_cost_plugin._CURRENT_FILE.set("tests/test_a.py")
    try:
        from sase.ace.testing import settle as settle_helpers

        pilot = _FakePilot()
        await settle_helpers.settle_pilot(pilot, _pilot_pause=_fake_pilot_pause)
        await settle_helpers.pause_until_cpu_idle(pilot, _pilot_pause=_fake_pilot_pause)
        recorder._record_item("tests/test_a.py", wall_seconds=1.0, cpu_seconds=0.5)
        payload = recorder._worker_payload()
    finally:
        _test_cost_plugin._CURRENT_FILE.reset(token)
        recorder._restore_patches()

    causes = payload["files"]["tests/test_a.py"]["causes"]
    assert causes["ace_settle_pilot"]["count"] == 1
    assert causes["ace_pause_until_cpu_idle"]["count"] == 1


def test_build_cost_record_summarizes_collection_cpu_seconds() -> None:
    record = build_cost_record(
        [
            {
                "worker_id": "gw0",
                "wall_seconds": 1.0,
                "cpu_seconds": 1.0,
                "collection_seconds": 1.0,
                "collection_cpu_seconds": 0.6,
                "peak_rss_kib": 100,
                "causes": {},
                "files": {},
            },
            {
                "worker_id": "gw1",
                "wall_seconds": 1.0,
                "cpu_seconds": 1.0,
                "collection_seconds": 1.0,
                "collection_cpu_seconds": 0.4,
                "peak_rss_kib": 100,
                "causes": {},
                "files": {},
            },
        ],
        mode="cost",
        worker_count=2,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert record["summary"]["collection_cpu_seconds"] == 1.0


def test_per_worker_normalization_divides_summed_actual_by_worker_count() -> None:
    record = {"summary": {"collection_cpu_seconds": 160.0}, "worker_count": 10}
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.0},
        "summary": {"collection_cpu_seconds": {"limit": 20.0, "per_worker": True}},
        "causes": {},
    }

    assert check_cost_budgets(record, budgets) == []

    budgets["summary"]["collection_cpu_seconds"]["limit"] = 15.0
    failures = check_cost_budgets(record, budgets)

    assert [failure.metric for failure in failures] == [
        "collection_cpu_seconds (per worker)"
    ]
    assert failures[0].actual == pytest.approx(16.0)


def test_per_worker_normalization_falls_back_when_worker_count_is_null() -> None:
    record = {
        "summary": {"collection_seconds": 40.0},
        "worker_count": None,
        "workers": [{"collection_seconds": 5.0}, {"collection_seconds": 5.0}],
    }
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.0},
        "summary": {"collection_seconds": {"limit": 20.0, "per_worker": True}},
        "causes": {},
    }

    assert check_cost_budgets(record, budgets) == []


def test_per_worker_normalization_never_divides_by_zero() -> None:
    record = {
        "summary": {"collection_seconds": 12.0},
        "worker_count": None,
        "workers": [],
    }
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.0},
        "summary": {"collection_seconds": {"limit": 12.0, "per_worker": True}},
        "causes": {},
    }

    assert check_cost_budgets(record, budgets) == []


_COMMITTED_BUDGETS: dict[str, Any] = load_cost_budgets(COMMITTED_BUDGETS_PATH)


def _committed_regression_cases() -> list[Any]:
    cases = []
    for metric, raw in sorted(_COMMITTED_BUDGETS["summary"].items()):
        limit = float(raw["limit"])
        per_worker = bool(raw.get("per_worker"))
        cases.append(
            pytest.param("summary", metric, limit, per_worker, id=f"summary-{metric}")
        )
    for cause, raw in sorted((_COMMITTED_BUDGETS.get("causes") or {}).items()):
        limit = float(raw["limit"])
        cases.append(pytest.param("causes", cause, limit, False, id=f"causes-{cause}"))
    return cases


@pytest.mark.parametrize("scope, key, limit, per_worker", _committed_regression_cases())
def test_every_committed_budget_flags_a_doubled_metric(
    scope: str, key: str, limit: float, per_worker: bool
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
        record = {"summary": {"causes": {key: {"count": 1, "seconds": limit * 2}}}}
        expected_metric = f"causes.{key}"

    failures = check_cost_budgets(record, _COMMITTED_BUDGETS)

    assert [failure.metric for failure in failures] == [expected_metric]


def test_committed_pre_epic_baseline_still_fails_recalibrated_budgets() -> None:
    baseline = load_cost_record(BASELINE_RECORDING_PATH)

    failures = check_cost_budgets(baseline, _COMMITTED_BUDGETS)

    assert [failure.metric for failure in failures] == [
        "causes.parser_create",
        "causes.textual_app_run_test_enter",
        "causes.yaml_load",
    ]


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
                "causes": {"parser_create": {"count": 2, "seconds": 0.5}},
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
    assert loaded["causes"]["parser_create"]["limit"] > 0
