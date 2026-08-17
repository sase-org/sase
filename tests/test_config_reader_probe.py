"""Tests for the opt-in ambient config-reader probe."""

from __future__ import annotations

from collections.abc import Iterator
import json
from pathlib import Path
import threading

import pytest

from sase.config import core as config_core
from sase.config.core import CONFIG_TOKEN_REFRESH_THREAD_NAME
from tests._config_reader_probe import (
    BETWEEN_TESTS_NODEID,
    ConfigReaderProbe,
    _combine_payloads,
)


_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def probe(tmp_path: Path) -> Iterator[ConfigReaderProbe]:
    instance = ConfigReaderProbe(
        tmp_path / "sase-config-readers.json",
        worker_dir=tmp_path / "workers",
    )
    instance.mark_baseline_threads()
    try:
        yield instance
    finally:
        instance.uninstall_wrappers()


def test_wrapper_records_non_main_thread_call(probe: ConfigReaderProbe) -> None:
    probe.install_wrappers()
    probe.set_current_nodeid("tests/test_a.py::test_a")
    started = threading.Event()
    done = threading.Event()

    def _run() -> None:
        started.set()
        config_core.load_merged_config()
        done.set()

    thread = threading.Thread(target=_run, name="ambient-config-reader")
    thread.start()
    assert started.wait(timeout=1.0)
    assert done.wait(timeout=2.0)
    thread.join(timeout=2.0)

    records = probe._payload()["ambient_reads"]
    assert isinstance(records, list)
    assert records
    record = next(
        item
        for item in records
        if item["thread_name"] == "ambient-config-reader"
        and item["function"] == "load_merged_config"
    )
    assert record["call_count"] == 1
    assert record["nodeids"] == ["tests/test_a.py::test_a"]
    assert record["originating_nodeid"] == "tests/test_a.py::test_a"
    assert record["poisoning_nodeids"] == []
    assert "load_merged_config" in str(record["stack"])


def test_main_thread_calls_are_not_recorded(probe: ConfigReaderProbe) -> None:
    probe.install_wrappers()
    probe.set_current_nodeid("tests/test_a.py::test_a")
    config_core.current_config_token()
    assert probe._payload()["ambient_reads"] == []


def test_refresh_worker_calls_are_not_ambient_reads(probe: ConfigReaderProbe) -> None:
    probe.install_wrappers()
    probe.set_current_nodeid("tests/test_a.py::test_a")
    done = threading.Event()

    def _run() -> None:
        config_core.clear_config_cache()
        done.set()

    thread = threading.Thread(target=_run, name=CONFIG_TOKEN_REFRESH_THREAD_NAME)
    thread.start()
    assert done.wait(timeout=2.0)
    thread.join(timeout=2.0)

    assert probe._payload()["ambient_reads"] == []


def test_cross_test_thread_is_attributed_to_origin_and_victim(
    probe: ConfigReaderProbe,
) -> None:
    started = threading.Event()
    hold = threading.Event()

    def _run() -> None:
        started.set()
        hold.wait(timeout=2.0)

    thread = threading.Thread(target=_run, name="leaked-poller")
    thread.start()
    assert started.wait(timeout=1.0)
    try:
        probe.observe_after_test("tests/test_a.py::test_owner")
        probe.observe_after_test("tests/test_b.py::test_victim")
        payload = probe._payload()
    finally:
        hold.set()
        thread.join(timeout=2.0)

    threads = payload["cross_test_threads"]
    assert isinstance(threads, list)
    assert len(threads) == 1
    record = threads[0]
    assert record["thread_name"] == "leaked-poller"
    assert record["originating_nodeid"] == "tests/test_a.py::test_owner"
    assert record["victim_nodeids"] == ["tests/test_b.py::test_victim"]


def test_refresh_worker_is_bucketed_separately(probe: ConfigReaderProbe) -> None:
    started = threading.Event()
    hold = threading.Event()

    def _run() -> None:
        started.set()
        hold.wait(timeout=2.0)

    thread = threading.Thread(target=_run, name=CONFIG_TOKEN_REFRESH_THREAD_NAME)
    thread.start()
    assert started.wait(timeout=1.0)
    try:
        probe.observe_after_test("tests/test_a.py::test_owner")
        probe.observe_after_test("tests/test_b.py::test_victim")
        payload = probe._payload()
    finally:
        hold.set()
        thread.join(timeout=2.0)

    assert payload["cross_test_threads"] == []
    workers = payload["refresh_workers"]
    assert isinstance(workers, list)
    assert len(workers) == 1
    record = workers[0]
    assert record["originating_nodeid"] == "tests/test_a.py::test_owner"
    assert record["victim_nodeids"] == ["tests/test_b.py::test_victim"]
    assert record["still_alive"] is True


def test_between_tests_read_is_poisoning(probe: ConfigReaderProbe) -> None:
    probe.install_wrappers()
    probe.set_current_nodeid("tests/test_a.py::test_owner")
    started = threading.Event()
    hold = threading.Event()
    read_during_gap = threading.Event()

    def _run() -> None:
        started.set()
        hold.wait(timeout=2.0)
        config_core.load_merged_config()
        read_during_gap.set()

    thread = threading.Thread(target=_run, name="gap-reader")
    thread.start()
    assert started.wait(timeout=1.0)
    probe.observe_after_test("tests/test_a.py::test_owner")
    probe.set_current_nodeid(None)
    hold.set()
    assert read_during_gap.wait(timeout=2.0)
    thread.join(timeout=2.0)

    records = probe._payload()["ambient_reads"]
    assert isinstance(records, list)
    record = next(item for item in records if item["thread_name"] == "gap-reader")
    assert BETWEEN_TESTS_NODEID in record["nodeids"]
    assert BETWEEN_TESTS_NODEID in record["poisoning_nodeids"]


def test_combined_report_merges_worker_payloads() -> None:
    report = _combine_payloads(
        [
            {
                "observed_tests": 2,
                "ambient_reads": [
                    {
                        "worker_id": "gw1",
                        "thread_name": "poller",
                        "function": "load_merged_config",
                        "call_count": 3,
                        "originating_nodeid": "tests/a.py::test_owner",
                        "poisoning_nodeids": ["tests/b.py::test_victim"],
                    }
                ],
                "cross_test_threads": [
                    {
                        "worker_id": "gw1",
                        "thread_name": "poller",
                        "originating_nodeid": "tests/a.py::test_owner",
                    }
                ],
                "refresh_workers": [],
                "errors": [],
            },
            {
                "observed_tests": 1,
                "ambient_reads": [],
                "cross_test_threads": [],
                "refresh_workers": [
                    {
                        "worker_id": "gw0",
                        "originating_nodeid": "tests/c.py::test_c",
                    }
                ],
                "errors": ["worker gw0 could not write payload"],
            },
        ]
    )

    assert report["summary"] == {
        "observed_tests": 3,
        "ambient_reader_calls": 3,
        "ambient_reader_records": 1,
        "poisoning_reads": 1,
        "cross_test_live_threads": 1,
        "timed_out_refresh_workers": 1,
    }
    assert report["errors"] == ["worker gw0 could not write payload"]
    assert [record["worker_id"] for record in report["refresh_workers"]] == ["gw0"]
    assert [record["worker_id"] for record in report["ambient_reads"]] == ["gw1"]


def test_worker_payload_is_written_to_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw7")
    detector = ConfigReaderProbe(
        tmp_path / "report.json",
        worker_dir=tmp_path / "workers",
    )

    assert detector._write_worker_payload() is None
    assert (tmp_path / "workers" / "gw7.json").is_file()


def test_cross_test_config_reader_is_reported_as_poisoning(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(_ROOT))
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("SASE_CONFIG_READER_WORKER_DIR", raising=False)
    report_path = pytester.path / "readers.json"
    pytester.makepyfile(
        """
        import threading
        import time

        from sase.config.core import load_merged_config

        _stop = threading.Event()

        def test_owner_starts_ambient_reader():
            def _run() -> None:
                while not _stop.wait(0.01):
                    load_merged_config()

            thread = threading.Thread(
                target=_run, name="ambient-config-reader", daemon=True
            )
            thread.start()
            time.sleep(0.02)

        def test_victim_runs_while_reader_is_live():
            deadline = time.perf_counter() + 0.5
            while time.perf_counter() < deadline:
                time.sleep(0.01)
            _stop.set()
        """
    )

    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-p",
        "tests._config_reader_probe",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--sase-detect-config-readers",
        f"--sase-config-reader-report={report_path}",
        timeout=60,
    )

    result.assert_outcomes(passed=2)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["poisoning_reads"] >= 1
    poisoning = [
        record
        for record in report["ambient_reads"]
        if record.get("thread_name") == "ambient-config-reader"
        and record.get("poisoning_nodeids")
    ]
    assert poisoning
    assert any(
        "test_victim_runs_while_reader_is_live" in nodeid
        for record in poisoning
        for nodeid in record["poisoning_nodeids"]
    )
