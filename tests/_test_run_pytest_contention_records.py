"""Tests for contention failure records and diagnostics."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests import _contention_plugin as contention_plugin
from tests._contention import (
    DIAGNOSTICS_ENV,
    FAILURES_ENV,
    FAILURE_DETAIL_LIMIT,
    NodeTally,
    append_failure_report,
    format_tally,
    read_failure_record,
    read_failures,
    start_failure_record,
    tally_failures,
    write_failures,
)
from tests._run_pytest_fixtures import load_run_pytest
from tests._run_pytest_contention_support import FakeSampler, install_fake_repeats
from tests._test_selection_health_store import STORE_ENV

ROOT = Path(__file__).resolve().parents[1]


def _isolate_contention_artifacts(
    runner: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    """Keep ``main(["contention"])`` off the live soak's artifact directory."""
    artifacts = tmp_path / "contention-artifacts"
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(tmp_path / "scratch"))
    monkeypatch.setattr(runner, "CONTENTION_ARTIFACT_DIRECTORY", artifacts)
    return artifacts


class _StubReport:
    def __init__(
        self,
        nodeid: str,
        *,
        failed: bool,
        when: str = "call",
        longrepr: str = "traceback",
    ) -> None:
        self.nodeid = nodeid
        self.failed = failed
        self.when = when
        self.longrepr = longrepr


def test_empty_tally_reports_the_clean_soak_as_a_result() -> None:
    report = format_tally([], repeat_count=6, red_repeats=[], duration=12.0)

    assert "0 node(s) failed across 6 repeat(s) in 12.0s" in report
    assert "red repeats: none" in report
    assert "no node failed in any repeat" in report


def test_recorded_failures_round_trip_deduplicated(tmp_path: Path) -> None:
    path = tmp_path / "repeat-01.json"

    write_failures(
        path, ["tests/b.py::test_b", "tests/a.py::test_a", "tests/a.py::test_a"]
    )

    assert read_failures(path) == ("tests/a.py::test_a", "tests/b.py::test_b")


def test_recorder_writes_test_failures_and_collection_errors(tmp_path: Path) -> None:
    path = tmp_path / "repeat-01.json"
    recorder = contention_plugin.ContentionFailureRecorder(path)

    recorder.pytest_runtest_logreport(_StubReport("tests/a.py::test_a", failed=True))
    recorder.pytest_runtest_logreport(_StubReport("tests/a.py::test_b", failed=False))
    recorder.pytest_collectreport(_StubReport("tests/broken.py", failed=True))
    recorder.pytest_collectreport(_StubReport("", failed=True))
    recorder.pytest_sessionfinish(exitstatus=1)

    assert read_failures(path) == ("tests/a.py::test_a", "tests/broken.py")
    record = read_failure_record(path)
    assert record is not None and record.complete
    assert {item["phase"] for item in record.reports} == {"call", "collect"}


def test_failure_reports_are_durable_before_session_finish_and_bounded(
    tmp_path: Path,
) -> None:
    path = tmp_path / "repeat-01.json"
    recorder = contention_plugin.ContentionFailureRecorder(path)

    recorder.pytest_runtest_logreport(
        _StubReport(
            "tests/a.py::test_a",
            failed=True,
            when="setup",
            longrepr="x" * (FAILURE_DETAIL_LIMIT + 100),
        )
    )

    partial = read_failure_record(path)
    assert partial is not None and not partial.complete
    assert read_failures(path) == ()
    assert partial.reports[0]["phase"] == "setup"
    assert len(partial.reports[0]["detail"]) == FAILURE_DETAIL_LIMIT
    assert partial.reports[0]["detail_truncated"] is True

    recorder.pytest_sessionfinish(exitstatus=1)
    completed = read_failure_record(path)
    assert completed is not None and completed.complete
    assert completed.exitstatus == 1
    assert read_failures(path) == ("tests/a.py::test_a",)


def test_failure_record_write_errors_do_not_escape_into_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "repeat-01.json"
    recorder = contention_plugin.ContentionFailureRecorder(path)

    def _fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("read-only diagnostic directory")

    monkeypatch.setattr(contention_plugin, "append_failure_report", _fail_write)
    recorder.pytest_runtest_logreport(_StubReport("tests/a.py::test_a", failed=True))
    recorder.pytest_sessionfinish(exitstatus=1)

    record = read_failure_record(path)
    assert record is not None and record.complete
    assert record.reports_unwritten == 1
    assert read_failures(path) == ()


def test_only_the_controller_registers_the_recorder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    monkeypatch.setenv(FAILURES_ENV, str(tmp_path / "repeat-01.json"))

    registered: list[str] = []

    class _StubManager:
        def register(self, _plugin: object, name: str) -> None:
            registered.append(name)

    class _StubConfig:
        pluginmanager = _StubManager()

    contention_plugin.pytest_configure(_StubConfig())  # type: ignore[arg-type]

    assert registered == []
    # The worker must leave the request alone for the controller to consume.
    assert FAILURES_ENV in os.environ

    monkeypatch.delenv("PYTEST_XDIST_WORKER")
    contention_plugin.pytest_configure(_StubConfig())  # type: ignore[arg-type]

    assert registered == ["sase-contention-recorder"]
    # Popped, so nested pytest subprocesses cannot overwrite the record.
    assert FAILURES_ENV not in os.environ
    parent_record = tmp_path / "repeat-01.json"
    before_nested = parent_record.read_text(encoding="utf-8")

    nested_test = tmp_path / "test_nested.py"
    nested_test.write_text(
        "import os\n"
        "def test_failure_record_request_is_not_inherited():\n"
        f"    assert {FAILURES_ENV!r} not in os.environ\n",
        encoding="utf-8",
    )
    nested = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-c",
            os.devnull,
            "--confcutdir",
            str(tmp_path),
            "-p",
            "tests._contention_plugin",
            str(nested_test),
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert nested.returncode == 0, nested.stdout + nested.stderr
    assert parent_record.read_text(encoding="utf-8") == before_nested


def test_each_repeat_gets_its_own_progress_record_and_one_sampler_watches_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "2")
    monkeypatch.delenv(runner.CONTENTION_SAMPLE_SECONDS_ENV, raising=False)
    sampler = FakeSampler()
    recorded = install_fake_repeats(
        runner, monkeypatch, tmp_path, [(0, ()), (0, ())], sampler
    )

    assert runner.main(["contention"]) == 0

    diagnostics = tmp_path / "contention-artifacts" / "diagnostics"
    assert len(sampler.starts) == 1 and sampler.stops == 1
    start = sampler.starts[0]
    assert start["out"] == diagnostics
    assert start["root_pid"] == os.getpid()
    assert start["interval"] == runner.DEFAULT_CONTENTION_SAMPLE_SECONDS
    assert set(start["paths"]) == {"scratch", "tmp", "workspace"}
    assert start["paths"]["scratch"] == tmp_path / "scratch"
    assert [repeat.env[DIAGNOSTICS_ENV] for repeat in recorded] == [
        str(diagnostics / "progress" / "repeat-01"),
        str(diagnostics / "progress" / "repeat-02"),
    ]
    # The request rides the child environment only, never this process's.
    assert DIAGNOSTICS_ENV not in os.environ
    assert "contention diagnostics:" in capsys.readouterr().out


def test_an_unavailable_sampler_changes_neither_the_run_nor_its_exit_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "1")
    install_fake_repeats(
        runner,
        monkeypatch,
        tmp_path,
        [(5, ("tests/t.py::test_red",))],
        FakeSampler(available=False),
    )

    assert runner.main(["contention"]) == 5
    output = capsys.readouterr().out
    assert "1/1  tests/t.py::test_red  (repeats 1)" in output
    assert "contention diagnostics:" not in output


def test_a_signalled_repeat_is_named_and_keeps_its_exit_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "2")
    sampler = FakeSampler()
    install_fake_repeats(
        runner, monkeypatch, tmp_path, [(-15, None), (1, ("tests/t.py::x",))], sampler
    )

    assert runner.main(["contention"]) == -15
    captured = capsys.readouterr()
    assert "contention repeat 1: pytest was killed by SIGTERM" in captured.err
    assert "red repeats: 1,2" in captured.out
    assert sampler.stops == 1


def test_interrupted_failure_reports_stay_separate_from_completed_tally(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "1")
    _isolate_contention_artifacts(runner, monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "start_sampler", FakeSampler().start)
    monkeypatch.setattr(runner, "_contention_shards", lambda *_a, **_k: None)

    def _interrupted(_command: list[str], **kwargs: Any) -> SimpleNamespace:
        failures_path = Path(kwargs["env"][FAILURES_ENV])
        start_failure_record(failures_path)
        append_failure_report(
            failures_path,
            nodeid="tests/t.py::test_before_cancel",
            phase="call",
            detail="AssertionError: evidence preserved",
        )
        return SimpleNamespace(returncode=-15)

    monkeypatch.setattr(runner.subprocess, "run", _interrupted)

    assert runner.main(["contention"]) == -15
    output = capsys.readouterr().out
    assert "0 node(s) failed across 0 completed repeat(s) of 1 requested" in output
    assert "partial failure evidence (excluded from the completed tally)" in output
    assert "[call] tests/t.py::test_before_cancel: AssertionError" in output


def test_nested_contention_does_not_clear_a_parent_soak_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """In-process nested soaks must not rmtree the live parent artifact dir."""
    runner = load_run_pytest()
    parent = _isolate_contention_artifacts(runner, monkeypatch, tmp_path)
    parent.mkdir(parents=True, exist_ok=True)
    marker = parent / "repeat-01.json"
    marker.write_text("parent-record\n", encoding="utf-8")
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "1")
    monkeypatch.setenv(runner.CONTENTION_ACTIVE_ENV, "1")
    monkeypatch.setattr(runner, "start_sampler", FakeSampler().start)
    monkeypatch.setattr(runner, "_contention_shards", lambda *_a, **_k: None)

    def _complete(_command: list[str], **kwargs: Any) -> SimpleNamespace:
        write_failures(Path(kwargs["env"][FAILURES_ENV]), ())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", _complete)

    assert runner.main(["contention"]) == 0
    assert marker.read_text(encoding="utf-8") == "parent-record\n"
    nested = parent / "nested" / str(os.getpid())
    assert (nested / "repeat-01.json").is_file()
    assert marker.parent == parent


def test_missing_record_after_zero_exit_is_not_a_clean_repeat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "1")
    install_fake_repeats(runner, monkeypatch, tmp_path, [(0, None)])

    assert runner.main(["contention"]) == int(pytest.ExitCode.INTERNAL_ERROR)
    captured = capsys.readouterr()
    assert "0 completed repeat(s) of 1 requested" in captured.out
    assert "no readable failure record" in captured.out
    assert "no completed failure record" in captured.err


def test_an_interrupted_soak_still_stops_its_sampler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "3")
    sampler = FakeSampler()
    install_fake_repeats(runner, monkeypatch, tmp_path, [(0, ())], sampler)

    def _interrupted(_command: list[str], **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner.subprocess, "run", _interrupted)

    assert runner.main(["contention"]) == int(pytest.ExitCode.INTERRUPTED)
    assert sampler.stops == 1


@pytest.mark.parametrize("value", ["0", "soon"])
def test_invalid_sample_interval_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.CONTENTION_SAMPLE_SECONDS_ENV, value)

    def _unexpected_start(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the soak started diagnostics despite a bad interval")

    monkeypatch.setattr(runner, "start_sampler", _unexpected_start)

    assert runner.main(["contention"]) == int(pytest.ExitCode.USAGE_ERROR)


def test_tally_orders_frequent_nodes_first_and_keeps_repeat_indices() -> None:
    tallies = tally_failures(
        [
            ("tests/a.py::test_one",),
            ("tests/b.py::test_two",),
            ("tests/b.py::test_two", "tests/a.py::test_one"),
            ("tests/b.py::test_two", "tests/c.py::test_three"),
        ]
    )

    assert tallies == (
        # Frequency first; ties break on node ID so the report is stable.
        NodeTally(nodeid="tests/b.py::test_two", failures=3, repeats=(2, 3, 4)),
        NodeTally(nodeid="tests/a.py::test_one", failures=2, repeats=(1, 3)),
        NodeTally(nodeid="tests/c.py::test_three", failures=1, repeats=(4,)),
    )


def test_unreadable_or_foreign_records_contribute_no_nodes(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    assert read_failures(missing) == ()

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    assert read_failures(malformed) == ()

    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({"schema": 99, "failures": ["x"]}), encoding="utf-8")
    assert read_failures(foreign) == ()
