"""Unit tests for the opt-in suite cost-attribution harness."""

from __future__ import annotations

import importlib.util
import json
import time
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
        "cpu_seconds": 0.0,
    }
    assert record["files"]["tests/test_a.py"]["node_count"] == 3


def test_build_cost_record_flat_rss_keys_mirror_the_curve() -> None:
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
                "causes": {},
                "files": {},
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
                "causes": {},
                "files": {},
            },
        ],
        mode="cost",
        worker_count=2,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    curve = record["summary"]["worker_rss_curve_kib"]
    assert record["summary"]["median_worker_rss_kib"] == curve["median"]
    assert (
        record["summary"]["post_collection_worker_rss_kib"] == curve["post_collection"]
    )


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


def test_check_cost_budgets_classifies_severity_by_family() -> None:
    record = {
        "summary": {
            "total_file_wall_seconds": 100.0,
            "total_file_cpu_seconds": 100.0,
            "peak_worker_rss_kib": 100.0,
            "causes": {
                "some_cause": {"count": 10, "seconds": 100.0, "cpu_seconds": 100.0},
            },
        },
    }
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.0, "ci": 0.0, "cpu": 0.0},
        "summary": {
            "total_file_wall_seconds": {"limit": 1.0},
            "total_file_cpu_seconds": {"limit": 1.0},
            "peak_worker_rss_kib": {"limit": 1.0},
        },
        "causes": {
            "some_cause": {"limit": 1.0, "cpu_limit": 1.0, "count_limit": 1},
        },
    }

    failures = {
        failure.metric: failure for failure in check_cost_budgets(record, budgets)
    }

    assert failures["total_file_wall_seconds"].severity == "advisory"
    assert failures["total_file_cpu_seconds"].severity == "hard"
    assert failures["peak_worker_rss_kib"].severity == "hard"
    assert failures["causes.some_cause"].severity == "advisory"
    assert failures["causes.some_cause.cpu"].severity == "hard"
    assert failures["causes.some_cause.count"].severity == "hard"


def test_check_cost_budgets_enforce_overrides_family_default() -> None:
    record = {"summary": {"total_file_wall_seconds": 100.0}}
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.0},
        "summary": {"total_file_wall_seconds": {"limit": 1.0, "enforce": "hard"}},
        "causes": {},
    }

    failures = check_cost_budgets(record, budgets)

    assert failures[0].severity == "hard"


def test_count_budget_has_no_tolerance() -> None:
    record = {
        "summary": {"causes": {"c": {"count": 10, "seconds": 0.0, "cpu_seconds": 0.0}}}
    }
    budgets = {
        "schema": 1,
        "tolerance": {"local": 0.5, "cpu": 0.5},
        "summary": {},
        "causes": {"c": {"count_limit": 10}},
    }

    assert check_cost_budgets(record, budgets) == []

    budgets["causes"]["c"]["count_limit"] = 9
    failures = check_cost_budgets(record, budgets)

    assert failures[0].metric == "causes.c.count"
    assert failures[0].tolerance == 0.0
    assert failures[0].allowed == 9.0


def test_cpu_budget_uses_cpu_tolerance() -> None:
    record = {
        "summary": {"causes": {"c": {"count": 1, "seconds": 0.0, "cpu_seconds": 11.5}}}
    }
    budgets = {
        "schema": 1,
        "tolerance": {"cpu": 0.10},
        "summary": {},
        "causes": {"c": {"cpu_limit": 10.0}},
    }

    failures = check_cost_budgets(record, budgets)

    assert failures[0].metric == "causes.c.cpu"
    assert failures[0].tolerance == 0.10
    assert failures[0].allowed == pytest.approx(11.0)


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


def test_cost_recorder_attributes_cpu_seconds_by_cause(tmp_path: Path) -> None:
    recorder = _test_cost_plugin.CostRecorder(tmp_path, mode="cost", worker_count=1)
    token = _test_cost_plugin._CURRENT_FILE.set("tests/test_a.py")
    try:
        with recorder.measure("cpu_bound_cause"):
            total = 0
            for i in range(2_000_000):
                total += i * i
        with recorder.measure("sleep_bound_cause"):
            time.sleep(0.05)  # sase-test-wait: need measurable wall time with ~0 CPU
        payload = recorder._worker_payload()
    finally:
        _test_cost_plugin._CURRENT_FILE.reset(token)
        recorder._restore_patches()

    cpu_cause = payload["causes"]["cpu_bound_cause"]
    sleep_cause = payload["causes"]["sleep_bound_cause"]
    assert cpu_cause["cpu_seconds"] > 0.0
    assert sleep_cause["cpu_seconds"] < sleep_cause["seconds"] / 2

    record = build_cost_record(
        [payload],
        mode="cost",
        worker_count=1,
        host="host",
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert record["summary"]["causes"]["cpu_bound_cause"]["cpu_seconds"] > 0.0
    assert (
        record["files"]["tests/test_a.py"]["causes"]["cpu_bound_cause"]["cpu_seconds"]
        > 0.0
    )


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
        "tolerance": {"local": 0.0, "cpu": 0.0},
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
