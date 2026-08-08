"""The opt-in contention soak lane in `tools/run_pytest`.

Two things are load-bearing here and neither is visible from a passing soak:
the lane must stay out of every governed and recorded path -- no suite-gate
lease, no selection-health record, unreachable from `just check` -- and the
per-node tally must attribute failures to the repeats they happened in, because
that attribution is the whole evidentiary value of a soak.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests import _contention_plugin as contention_plugin
from tests._contention import (
    FAILURES_ENV,
    NodeTally,
    format_tally,
    read_failures,
    tally_failures,
    write_failures,
)
from tests._run_pytest_fixtures import (
    isolate_run_pytest_environment,  # noqa: F401 (registers autouse env-isolation fixture)
    load_run_pytest,
)
from tests._test_selection_health_store import RECORD_ENV, STORE_ENV


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]


class RecordedRepeat:
    """One intercepted repeat: the command, its environment, and its verdict."""

    def __init__(self, command: list[str], env: dict[str, str]) -> None:
        self.command = command
        self.env = env

    def complete(self, failures: tuple[str, ...] | None) -> None:
        if failures is not None:
            write_failures(Path(self.env[FAILURES_ENV]), failures)


def _install_fake_repeats(
    runner: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    outcomes: list[tuple[int, tuple[str, ...] | None]],
) -> list[RecordedRepeat]:
    """Stand in for the pytest subprocess each repeat launches.

    Each entry in ``outcomes`` is one repeat's ``(exit status, failing node
    IDs)``; a ``None`` node tuple is a repeat that wrote no record at all,
    which is what a hard crash leaves behind.
    """
    recorded: list[RecordedRepeat] = []
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(tmp_path / "scratch"))
    monkeypatch.setattr(
        runner, "CONTENTION_ARTIFACT_DIRECTORY", tmp_path / "contention-artifacts"
    )

    class _Result:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def _fake_run(command: list[str], **kwargs: Any) -> _Result:
        repeat = RecordedRepeat(list(command), dict(kwargs["env"]))
        returncode, failures = outcomes[len(recorded)]
        recorded.append(repeat)
        repeat.complete(failures)
        return _Result(returncode)

    monkeypatch.setattr(runner.subprocess, "run", _fake_run)
    return recorded


def test_contention_mode_runs_the_default_lane_selection() -> None:
    runner = load_run_pytest()

    command = runner._pytest_command(
        runner.CONTENTION_MODE, [], worker_count=26, serial=False
    )

    assert command[3:6] == ["-n", "26", "--dist=worksteal"]
    assert command[-2:] == ["-m", runner.FAST_MARKER_EXPRESSION]


def test_contention_stays_out_of_the_recorded_and_full_lane_modes() -> None:
    runner = load_run_pytest()

    assert runner.CONTENTION_MODE not in runner.FULL_LANE_MODES
    assert runner.CONTENTION_MODE not in runner.TIMINGS_RECORDING_MODES
    assert runner.CONTENTION_MODE not in runner.SERIAL_MODES
    assert runner._full_lane_recording_args(runner.CONTENTION_MODE) == []
    assert runner._timings_pytest_args(runner.CONTENTION_MODE) == []


@pytest.mark.parametrize("recipe", ["check", "check-full"])
def test_contention_is_unreachable_from_the_verification_recipes(recipe: str) -> None:
    """The soak stays opt-in: a mandatory gate must not starve the host.

    Asserted against `just --dry-run`, not the Justfile text, so an indirect
    dependency added later is caught too.
    """
    dry_run = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "--dry-run", recipe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    output = dry_run.stdout + dry_run.stderr
    assert "test-contention" not in output
    assert "run_pytest contention" not in output


def test_repeat_runs_neither_lease_the_gate_nor_record_health(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.delenv(runner.CONTENTION_REPEAT_ENV, raising=False)
    monkeypatch.setenv(runner.CONTENTION_WORKERS_ENV, "26")
    recorded = _install_fake_repeats(
        runner, monkeypatch, tmp_path, [(0, ()), (0, ()), (0, ())]
    )

    def _unexpected_lease(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the contention soak leased suite-gate tokens")

    monkeypatch.setattr(runner, "_parallel_worker_grant", _unexpected_lease)

    assert runner.main(["contention"]) == 0
    assert len(recorded) == runner.DEFAULT_CONTENTION_REPEAT
    for repeat in recorded:
        assert repeat.env["SASE_TEST_GATE_DISABLED"] == "1"
        assert repeat.env[runner.HEALTH_DISABLED_ENV] == "1"
        assert RECORD_ENV not in repeat.env
        assert "-p" in repeat.command
        assert runner.CONTENTION_PLUGIN_MODULE in repeat.command


def test_repeat_count_and_selector_subset_are_honoured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "2")
    monkeypatch.setenv(runner.CONTENTION_WORKERS_ENV, "9")
    recorded = _install_fake_repeats(runner, monkeypatch, tmp_path, [(0, ()), (0, ())])

    assert runner.main(["contention", "--", "tests/test_agent_lanes.py"]) == 0
    assert len(recorded) == 2
    for repeat in recorded:
        assert repeat.command[3:5] == ["-n", "9"]
        assert repeat.command[-1] == "tests/test_agent_lanes.py"
    # Each repeat gets its own record, so the tally can attribute a node to one.
    paths = {repeat.env[FAILURES_ENV] for repeat in recorded}
    assert len(paths) == 2


def test_red_soak_returns_the_first_repeat_exit_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "3")
    _install_fake_repeats(
        runner,
        monkeypatch,
        tmp_path,
        [
            (0, ()),
            (1, ("tests/t.py::test_flaky",)),
            (1, ("tests/t.py::test_flaky", "tests/t.py::test_other")),
        ],
    )

    assert runner.main(["contention"]) == 1
    report = capsys.readouterr().out
    assert "2/3  tests/t.py::test_flaky  (repeats 2,3)" in report
    assert "1/3  tests/t.py::test_other  (repeats 3)" in report
    assert "red repeats: 2,3" in report


def test_stale_records_from_a_longer_soak_are_cleared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "health-store"))
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, "1")
    _install_fake_repeats(runner, monkeypatch, tmp_path, [(0, ())])
    stale = tmp_path / "contention-artifacts" / "repeat-02.json"
    write_failures(stale, ("tests/t.py::test_from_a_previous_soak",))

    assert runner.main(["contention"]) == 0
    assert not stale.exists()
    assert "test_from_a_previous_soak" not in capsys.readouterr().out


@pytest.mark.parametrize("value", ["0", "-2", "many"])
def test_invalid_repeat_count_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(runner.CONTENTION_REPEAT_ENV, value)

    assert runner.main(["contention"]) == int(pytest.ExitCode.USAGE_ERROR)


def test_worker_width_falls_back_to_the_general_knob_then_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_run_pytest()
    monkeypatch.delenv(runner.CONTENTION_WORKERS_ENV, raising=False)
    monkeypatch.delenv("SASE_PYTEST_WORKERS", raising=False)
    assert runner._contention_worker_count() == runner.DEFAULT_CONTENTION_WORKERS

    monkeypatch.setenv("SASE_PYTEST_WORKERS", "12")
    assert runner._contention_worker_count() == 12

    monkeypatch.setenv(runner.CONTENTION_WORKERS_ENV, "40")
    assert runner._contention_worker_count() == 40


def test_numprocesses_is_rejected_with_the_lane_specific_remedy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()

    def _unexpected_run(_command: list[str], **_kwargs: object) -> None:
        raise AssertionError("the soak launched pytest despite a rejected width")

    monkeypatch.setattr(runner.subprocess, "run", _unexpected_run)

    assert runner.main(["contention", "--", "-n", "4"]) == int(
        pytest.ExitCode.USAGE_ERROR
    )
    assert runner.CONTENTION_WORKERS_ENV in capsys.readouterr().err


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


def test_empty_tally_reports_the_clean_soak_as_a_result() -> None:
    report = format_tally([], repeat_count=6, red_repeats=[], duration=12.0)

    assert "0 node(s) failed across 6 repeat(s) in 12.0s" in report
    assert "red repeats: none" in report
    assert "no node failed in any repeat" in report


def test_unreadable_or_foreign_records_contribute_no_nodes(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    assert read_failures(missing) == ()

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    assert read_failures(malformed) == ()

    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({"schema": 99, "failures": ["x"]}), encoding="utf-8")
    assert read_failures(foreign) == ()


def test_recorded_failures_round_trip_deduplicated(tmp_path: Path) -> None:
    path = tmp_path / "repeat-01.json"

    write_failures(
        path, ["tests/b.py::test_b", "tests/a.py::test_a", "tests/a.py::test_a"]
    )

    assert read_failures(path) == ("tests/a.py::test_a", "tests/b.py::test_b")


class _StubReport:
    def __init__(self, nodeid: str, *, failed: bool) -> None:
        self.nodeid = nodeid
        self.failed = failed


def test_recorder_writes_test_failures_and_collection_errors(tmp_path: Path) -> None:
    path = tmp_path / "repeat-01.json"
    recorder = contention_plugin.ContentionFailureRecorder(path)

    recorder.pytest_runtest_logreport(_StubReport("tests/a.py::test_a", failed=True))
    recorder.pytest_runtest_logreport(_StubReport("tests/a.py::test_b", failed=False))
    recorder.pytest_collectreport(_StubReport("tests/broken.py", failed=True))
    recorder.pytest_collectreport(_StubReport("", failed=True))
    recorder.pytest_sessionfinish()

    assert read_failures(path) == ("tests/a.py::test_a", "tests/broken.py")


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
