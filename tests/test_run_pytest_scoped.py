"""Scoped (diff-selected) mode in `tools/run_pytest`.

Scoped mode runs a selection serially in a child process instead of exec'ing a
governed parallel lane, so it owns its own manifest, its own escalation
handoff, and its own refusals of the parallel-lane knobs. These tests pin all
three.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._run_pytest_fixtures import (
    forbid_pytest_launch,
    install_scoped_selection,
    isolate_run_pytest_environment,  # noqa: F401 (registers autouse env-isolation fixture)
    load_run_pytest,
    scoped_selection,
)
from tests._test_selection_gear import REFUSED_TOKENS_UNAVAILABLE


pytestmark = pytest.mark.contract


def test_scoped_mode_selects_fast_markers_without_xdist() -> None:
    runner = load_run_pytest()

    result = runner._pytest_command("scoped", ["tests/test_repeat_launcher.py"])

    assert "-n" not in result
    assert not any(arg.startswith("--dist") for arg in result)
    assert result[-3:] == [
        "-m",
        runner.FAST_MARKER_EXPRESSION,
        "tests/test_repeat_launcher.py",
    ]


def test_scoped_mode_runs_the_selection_serially_and_never_acquires(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    selected = ("tests/test_alpha.py", "tests/test_beta.py")
    manifest_path = install_scoped_selection(
        runner, monkeypatch, tmp_path, scoped_selection(runner, selected=selected)
    )
    observed: dict[str, object] = {}

    def _unexpected_grant() -> None:
        raise AssertionError("scoped mode attempted token acquisition")

    def _unexpected_execv(_executable: str, _command: list[str]) -> None:
        raise AssertionError("scoped mode exec'd instead of waiting for pytest")

    class _Completed:
        returncode = 0

    def _run(command: list[str], **kwargs: object) -> _Completed:
        observed["command"] = command
        observed["env"] = kwargs.get("env")
        return _Completed()

    monkeypatch.setattr(runner, "_parallel_worker_grant", _unexpected_grant)
    monkeypatch.setattr(runner.os, "execv", _unexpected_execv)
    monkeypatch.setattr(runner.subprocess, "run", _run)

    assert runner.main(["scoped"]) == 0

    command = observed["command"]
    assert isinstance(command, list)
    assert "-n" not in command
    assert not any(arg.startswith("--dist") for arg in command)
    assert command[-(4 + len(selected)) :] == [
        "-m",
        runner.FAST_MARKER_EXPRESSION,
        # A scoped run feeds the cost model the durations of the files the
        # lane actually touches; it still takes no lease to do it.
        "-p",
        runner.TIMINGS_PLUGIN_MODULE,
        *selected,
    ]
    environment = observed["env"]
    assert isinstance(environment, dict)
    assert runner.TIMINGS_RECORD_ENV in environment
    assert environment["SASE_TEST_GATE_DISABLED"] == "1"
    assert "SASE_TEST_GATE_DISABLED" not in runner.os.environ

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["outcome"] == "passed"
    assert manifest["duration"] >= 0
    assert manifest["selected"] == list(selected)


def test_scoped_mode_reports_a_failing_selection_in_the_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    manifest_path = install_scoped_selection(
        runner,
        monkeypatch,
        tmp_path,
        scoped_selection(runner, selected=("tests/test_alpha.py",)),
    )

    class _Completed:
        returncode = 1

    monkeypatch.setattr(
        runner.subprocess, "run", lambda *_args, **_kwargs: _Completed()
    )

    assert runner.main(["scoped"]) == 1
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["outcome"] == "failed"


def test_scoped_escalation_runs_the_governed_fast_lane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)
    install_scoped_selection(
        runner,
        monkeypatch,
        tmp_path,
        scoped_selection(runner, escalated=True, rules=("justfile",)),
    )
    observed: dict[str, object] = {}

    class ExecCalled(Exception):
        pass

    def _execv(_executable: str, command: list[str]) -> None:
        observed["command"] = command
        raise ExecCalled

    def _unexpected_run(command: list[str], **kwargs: object) -> object:
        if "pytest" in command:
            raise AssertionError("an escalated run must not stay in the serial lane")
        # Health recording resolves HEAD through git; let that through.
        return _real_subprocess_run(command, **kwargs)

    _real_subprocess_run = runner.subprocess.run
    monkeypatch.setattr(runner, "_parallel_worker_grant", lambda: (7, None))
    monkeypatch.setattr(runner.os, "execv", _execv)
    monkeypatch.setattr(runner.subprocess, "run", _unexpected_run)

    with pytest.raises(ExecCalled):
        runner.main(["scoped"])

    assert observed["command"] == runner._pytest_command(
        "fast",
        ["-p", runner.TIMINGS_PLUGIN_MODULE, "-p", runner.HEALTH_PLUGIN_MODULE],
        worker_count=7,
        distribution_mode="worksteal",
    )
    assert "escalating to the governed full test lane" in capsys.readouterr().err


class _FakeLease:
    """Stands in for a granted `WorkerTokenLease` without touching a pool."""

    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _ExecCalled(Exception):
    """Raised in place of the `execv` that would replace the test process."""


def _exec_called(_executable: str, _command: list[str]) -> None:
    raise _ExecCalled


def _refuse_exec(_executable: str, _command: list[str]) -> None:
    raise AssertionError("scoped mode exec'd instead of waiting for pytest")


def test_scoped_over_budget_selection_runs_at_the_granted_width(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The middle gear: a leased width instead of the whole suite."""
    runner = load_run_pytest()
    monkeypatch.delenv(runner.PYTEST_DIST_ENV, raising=False)
    candidate = ("tests/test_alpha.py", "tests/test_beta.py")
    manifest_path = install_scoped_selection(
        runner,
        monkeypatch,
        tmp_path,
        scoped_selection(
            runner,
            escalated=True,
            rules=("serial-budget-exceeded",),
            gear_candidate=candidate,
        ),
    )
    lease = _FakeLease()
    observed: dict[str, object] = {}

    class _Completed:
        returncode = 0

    def _run(command: list[str], **kwargs: object) -> _Completed:
        observed["command"] = command
        observed["env"] = kwargs.get("env")
        return _Completed()

    monkeypatch.setattr(
        runner,
        "engage_scoped_gear",
        lambda **_kwargs: (runner.ScopedGear(attempted=True, worker_count=3), lease),
    )
    monkeypatch.setattr(runner.os, "execv", _refuse_exec)
    monkeypatch.setattr(runner.subprocess, "run", _run)

    assert runner.main(["scoped"]) == 0

    command = observed["command"]
    assert isinstance(command, list)
    assert command[3:6] == ["-n", "3", "--dist=worksteal"]
    assert command[-2:] == list(candidate)
    # The gear's own lease marks the child governed; forcing the flag on top
    # would claim an exemption the lease is what paid for.
    environment = observed["env"]
    assert isinstance(environment, dict)
    assert "SASE_TEST_GATE_DISABLED" not in environment
    assert lease.released

    error = capsys.readouterr().err
    assert "middle gear: running the over-budget selection at 3 worker(s)" in error
    assert "escalating to the governed full test lane" not in error

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["escalated"] is False
    assert manifest["selected"] == list(candidate)
    assert manifest["selected_count"] == 2
    assert manifest["outcome"] == "passed"
    assert manifest["gear"]["granted"] is True
    assert manifest["gear"]["worker_count"] == 3


def test_scoped_over_budget_selection_escalates_when_the_gear_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    manifest_path = install_scoped_selection(
        runner,
        monkeypatch,
        tmp_path,
        scoped_selection(
            runner,
            escalated=True,
            rules=("serial-budget-exceeded",),
            gear_candidate=("tests/test_alpha.py",),
        ),
    )
    refused = runner.ScopedGear(attempted=True, reason=REFUSED_TOKENS_UNAVAILABLE)

    monkeypatch.setattr(runner, "engage_scoped_gear", lambda **_kwargs: (refused, None))
    monkeypatch.setattr(runner, "_parallel_worker_grant", lambda: (7, None))
    monkeypatch.setattr(runner.os, "execv", _exec_called)

    with pytest.raises(_ExecCalled):
        runner.main(["scoped"])

    error = capsys.readouterr().err
    assert "middle gear: no bounded lease (tokens-unavailable)" in error
    assert "escalating to the governed full test lane" in error

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["escalated"] is True
    assert manifest["outcome"] == "escalated"
    assert manifest["gear"]["granted"] is False
    assert manifest["gear"]["reason"] == REFUSED_TOKENS_UNAVAILABLE


def test_scoped_change_set_escalation_is_never_offered_to_the_gear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A rule that distrusts the closure is not answered by more workers."""
    runner = load_run_pytest()
    manifest_path = install_scoped_selection(
        runner,
        monkeypatch,
        tmp_path,
        scoped_selection(runner, escalated=True, rules=("root-conftest",)),
    )

    def _unexpected_gear(**_kwargs: object) -> None:
        raise AssertionError("a change-set escalation reached the middle gear")

    monkeypatch.setattr(runner, "engage_scoped_gear", _unexpected_gear)
    monkeypatch.setattr(runner, "_parallel_worker_grant", lambda: (7, None))
    monkeypatch.setattr(runner.os, "execv", _exec_called)

    with pytest.raises(_ExecCalled):
        runner.main(["scoped"])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["escalated"] is True
    assert "gear" not in manifest


def test_scoped_empty_selection_exits_zero_without_running_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    manifest_path = install_scoped_selection(
        runner, monkeypatch, tmp_path, scoped_selection(runner)
    )
    forbid_pytest_launch(runner, monkeypatch)

    assert runner.main(["scoped"]) == 0
    assert "no test files selected" in capsys.readouterr().err
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["outcome"] == "empty"
    assert manifest["duration"] == 0.0


def test_scoped_mode_rejects_explicit_xdist_count(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    install_scoped_selection(runner, monkeypatch, tmp_path, scoped_selection(runner))
    forbid_pytest_launch(runner, monkeypatch)

    assert runner.main(["scoped", "-n", "4"]) == int(pytest.ExitCode.USAGE_ERROR)
    assert "just check-full" in capsys.readouterr().err


def test_scoped_mode_rejects_exact_worker_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    install_scoped_selection(runner, monkeypatch, tmp_path, scoped_selection(runner))
    forbid_pytest_launch(runner, monkeypatch)
    monkeypatch.setenv("SASE_PYTEST_WORKERS", "8")

    assert runner.main(["scoped"]) == int(pytest.ExitCode.USAGE_ERROR)
    error = capsys.readouterr().err
    assert "SASE_PYTEST_WORKERS does not apply" in error
    assert "just check-full" in error


def test_scoped_selection_failure_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = load_run_pytest()
    install_scoped_selection(runner, monkeypatch, tmp_path, scoped_selection(runner))
    forbid_pytest_launch(runner, monkeypatch)

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise runner.SelectionError("SASE_TEST_SELECTION_DEPTH must be an integer")

    monkeypatch.setattr(runner, "select_tests", _explode)

    assert runner.main(["scoped"]) == int(pytest.ExitCode.USAGE_ERROR)
    assert "test selection failed" in capsys.readouterr().err


def _demand_channel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    demand_path = tmp_path / "demand.jsonl"
    monkeypatch.setenv("SASE_TOOL_RUN_DEMAND", str(demand_path))
    monkeypatch.setenv("SASE_TOOL_RUN_ID", "run-1")
    return demand_path


def _grants(demand_path: Path) -> list:
    return [
        json.loads(line)["grant"]
        for line in demand_path.read_text(encoding="utf-8").splitlines()
    ]


def test_scoped_gear_grant_is_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    demand_path = _demand_channel(monkeypatch, tmp_path)
    candidate = ("tests/test_alpha.py", "tests/test_beta.py")
    install_scoped_selection(
        runner,
        monkeypatch,
        tmp_path,
        scoped_selection(
            runner,
            escalated=True,
            rules=("serial-budget-exceeded",),
            gear_candidate=candidate,
        ),
    )
    lease = _FakeLease()

    class _Completed:
        returncode = 0

    monkeypatch.setattr(
        runner,
        "engage_scoped_gear",
        lambda **_kwargs: (runner.ScopedGear(attempted=True, worker_count=3), lease),
    )
    monkeypatch.setattr(runner.os, "execv", _refuse_exec)
    monkeypatch.setattr(
        runner.subprocess, "run", lambda *_args, **_kwargs: _Completed()
    )

    assert runner.main(["scoped"]) == 0

    grants = _grants(demand_path)
    assert len(grants) == 1
    grant = grants[0]
    assert grant["source"] == "pytest"
    assert grant["lane"] == "scoped"
    assert grant["path"] == "gear"
    assert grant["granted"] == 3
    assert grant["requested_floor"] == runner.SCOPED_WORKER_FLOOR
    assert grant["selected_files"] == 2
    assert grant["escalated_from"] is None


def test_scoped_serial_run_records_a_single_worker_grant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    demand_path = _demand_channel(monkeypatch, tmp_path)
    selected = ("tests/test_alpha.py", "tests/test_beta.py")
    install_scoped_selection(
        runner, monkeypatch, tmp_path, scoped_selection(runner, selected=selected)
    )

    class _Completed:
        returncode = 0

    def _unexpected_grant() -> object:
        raise AssertionError("scoped serial mode attempted token acquisition")

    monkeypatch.setattr(runner, "_parallel_worker_grant", _unexpected_grant)
    monkeypatch.setattr(runner.os, "execv", _refuse_exec)
    monkeypatch.setattr(
        runner.subprocess, "run", lambda *_args, **_kwargs: _Completed()
    )

    assert runner.main(["scoped"]) == 0

    grants = _grants(demand_path)
    assert len(grants) == 1
    grant = grants[0]
    assert grant["lane"] == "scoped"
    assert grant["path"] == "serial"
    assert grant["granted"] == 1
    assert grant["selected_files"] == 2


def test_scoped_escalation_attributes_the_full_lane_grant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    install_scoped_selection(
        runner,
        monkeypatch,
        tmp_path,
        scoped_selection(runner, escalated=True, rules=("justfile",)),
    )
    captured: dict[str, object] = {}

    class ExecCalled(Exception):
        pass

    def _execv(_executable: str, _command: list[str]) -> None:
        raise ExecCalled

    def _grant() -> tuple[int, None]:
        captured["lane"] = runner._GRANT_LANE
        captured["escalated_from"] = runner._GRANT_ESCALATED_FROM
        return (7, None)

    monkeypatch.setattr(runner, "_parallel_worker_grant", _grant)
    monkeypatch.setattr(runner.os, "execv", _execv)

    _real_subprocess_run = runner.subprocess.run

    def _unexpected_run(command: list[str], **kwargs: object) -> object:
        if "pytest" in command:
            raise AssertionError("an escalated run must not stay in the serial lane")
        # Health recording resolves HEAD through git; let that through.
        return _real_subprocess_run(command, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", _unexpected_run)

    with pytest.raises(ExecCalled):
        runner.main(["scoped"])

    assert captured == {"lane": "fast", "escalated_from": "scoped"}
