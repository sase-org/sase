"""Tests for the opt-in global-state leak detector."""

from __future__ import annotations

from pathlib import Path

from tests._global_state_leak_detector import GlobalStateLeakDetector, _combine_payloads
from tests._global_state_leaks.reporting import _poisoning_log_lines


def test_combined_report_counts_poisoning_and_warming() -> None:
    report = _combine_payloads(
        [
            {
                "observed_tests": 2,
                "warming_counts": {"global": 3},
                "cooling_counts": {"cache": 1},
                "invalidation_counts": {"global": 2},
                "records": [
                    {
                        "worker_id": "gw1",
                        "worker_order": 2,
                        "nodeid": "tests/test_a.py::test_a",
                        "changes": [{"kind": "global"}, {"kind": "cache"}],
                    }
                ],
            },
            {
                "observed_tests": 1,
                "warming_counts": {"cache": 4},
                "cooling_counts": {"global": 5},
                "invalidation_counts": {"cache": 6},
                "records": [],
            },
        ]
    )

    assert report["summary"] == {
        "observed_tests": 3,
        "tests_with_poisoning": 1,
        "poisoning_changes": 2,
        "warming_changes_filtered": 7,
        "warming_by_kind": {"cache": 4, "global": 3},
        "cooling_changes_filtered": 6,
        "cooling_by_kind": {"cache": 1, "global": 5},
        "invalidation_changes_filtered": 8,
        "invalidation_by_kind": {"cache": 6, "global": 2},
    }


def test_combined_report_sorts_by_worker_execution_order() -> None:
    report = _combine_payloads(
        [
            {
                "observed_tests": 2,
                "records": [
                    {
                        "worker_id": "gw1",
                        "worker_order": 2,
                        "nodeid": "tests/test_b.py::test_b",
                        "changes": [{"kind": "global"}],
                    },
                    {
                        "worker_id": "gw1",
                        "worker_order": 1,
                        "nodeid": "tests/test_a.py::test_a",
                        "changes": [{"kind": "global"}],
                    },
                ],
            },
            {
                "observed_tests": 1,
                "records": [
                    {
                        "worker_id": "gw0",
                        "worker_order": 1,
                        "nodeid": "tests/test_c.py::test_c",
                        "changes": [{"kind": "global"}],
                    }
                ],
            },
        ]
    )

    assert [
        (record["worker_id"], record["worker_order"], record["nodeid"])
        for record in report["poisoning"]
    ] == [
        ("gw0", 1, "tests/test_c.py::test_c"),
        ("gw1", 1, "tests/test_a.py::test_a"),
        ("gw1", 2, "tests/test_b.py::test_b"),
    ]


def test_combined_report_carries_worker_errors() -> None:
    report = _combine_payloads(
        [
            {
                "observed_tests": 1,
                "records": [],
                "errors": ["worker gw0 could not write payload"],
            }
        ]
    )

    assert report["errors"] == ["worker gw0 could not write payload"]


def test_worker_payload_is_written_to_sidecar(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw7")
    detector = GlobalStateLeakDetector(
        tmp_path / "report.json",
        worker_dir=tmp_path / "workers",
    )

    assert detector._write_worker_payload() is None

    assert (tmp_path / "workers" / "gw7.json").is_file()


def test_poisoning_log_lines_name_nodeids_and_change_kinds() -> None:
    lines = _poisoning_log_lines(
        {
            "poisoning": [
                {
                    "nodeid": "tests/foo.py::test_a",
                    "changes": [{"kind": "cwd", "name": "os.getcwd()"}],
                },
                {
                    "nodeid": "tests/foo.py::test_b",
                    "changes": [{"kind": "global", "name": "sase._LEAK"}],
                },
            ]
        }
    )
    assert lines == [
        "tests/foo.py::test_a (cwd:os.getcwd())",
        "tests/foo.py::test_b (global:sase._LEAK)",
    ]
    assert _poisoning_log_lines({"poisoning": []}) == []
    truncated = _poisoning_log_lines(
        {
            "poisoning": [
                {"nodeid": f"tests/foo.py::test_{index}", "changes": []}
                for index in range(3)
            ]
        },
        limit=2,
    )
    assert truncated[-1] == "... 1 more poisoning test(s)"
