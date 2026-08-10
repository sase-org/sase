"""Unit tests for the opt-in suite cost-attribution harness."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

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

    assert budgets["summary"]["collection_seconds"]["limit"] == 15.0


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
