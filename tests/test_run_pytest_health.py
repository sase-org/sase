"""Tests for the selection-health recording wired into `tools/run_pytest`.

The runner is the only component that knows a scoped run's duration and
outcome, and the only one positioned to arm the full-lane failure recorder
before `execv` takes the process away. These tests pin both handoffs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._run_pytest_fixtures import (
    health_store,
    install_scoped_selection,
    load_run_pytest,
    scoped_selection,
)
from tests._test_selection_health import STORE_ENV, load_records


pytestmark = pytest.mark.contract


def test_scoped_run_lands_in_the_durable_health_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    install_scoped_selection(
        runner,
        monkeypatch,
        tmp_path,
        scoped_selection(runner, selected=("tests/test_alpha.py",)),
    )

    class _Completed:
        returncode = 0

    monkeypatch.setattr(runner.subprocess, "run", lambda *_a, **_k: _Completed())

    assert runner.main(["scoped"]) == 0

    records = load_records(health_store(tmp_path))
    assert len(records.selections) == 1
    selection = records.selections[0]
    assert selection.outcome == "passed"
    assert selection.selected == frozenset({"tests/test_alpha.py"})
    assert selection.workspace == str(runner.REPO_ROOT.resolve())


def test_escalated_scoped_run_is_recorded_before_the_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    install_scoped_selection(
        runner,
        monkeypatch,
        tmp_path,
        scoped_selection(runner, escalated=True, rules=("justfile",)),
    )

    class ExecCalled(Exception):
        pass

    def _execv(_executable: str, _command: list[str]) -> None:
        raise ExecCalled

    monkeypatch.setattr(runner, "_parallel_worker_grant", lambda: (7, None))
    monkeypatch.setattr(runner.os, "execv", _execv)

    with pytest.raises(ExecCalled):
        runner.main(["scoped"])

    records = load_records(health_store(tmp_path))
    assert [record.outcome for record in records.selections] == ["escalated"]
    assert records.selections[0].escalated is True


def test_full_lane_arms_the_failure_recorder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(health_store(tmp_path)))
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(tmp_path / "scratch"))
    monkeypatch.delenv(runner.HEALTH_DISABLED_ENV, raising=False)
    monkeypatch.setattr(runner, "_parallel_worker_grant", lambda: (2, None))
    observed: dict[str, object] = {}

    class ExecCalled(Exception):
        pass

    def _execv(_executable: str, command: list[str]) -> None:
        observed["command"] = command
        observed["request"] = runner.os.environ.get(runner.RECORD_ENV)
        raise ExecCalled

    monkeypatch.setattr(runner.os, "execv", _execv)

    with pytest.raises(ExecCalled):
        runner.main(["fast"])

    command = observed["command"]
    assert isinstance(command, list)
    assert command[-2:] == ["-p", runner.HEALTH_PLUGIN_MODULE]
    request = json.loads(str(observed["request"]))
    assert request["mode"] == "fast"
    assert Path(request["path"]).parent == health_store(tmp_path)
    assert Path(request["path"]).name.endswith("-full-run.json")
    # Both halves of the correlation identity are resolved in the parent, and
    # the change set is the selector's own computation, not an approximation.
    assert request["workspace"] == str(runner.REPO_ROOT.resolve())
    assert request["changed_files"] == sorted(
        set(
            runner.compute_change_set(
                runner.REPO_ROOT, runner.SelectionOptions.from_environment().base_ref
            ).paths
        )
    )


def test_health_recording_can_be_switched_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runner = load_run_pytest()
    monkeypatch.setenv(STORE_ENV, str(health_store(tmp_path)))
    monkeypatch.setenv(runner.PYTEST_TMPDIR_ENV, str(tmp_path / "scratch"))
    monkeypatch.setenv(runner.HEALTH_DISABLED_ENV, "1")
    monkeypatch.delenv(runner.RECORD_ENV, raising=False)
    monkeypatch.setattr(runner, "_parallel_worker_grant", lambda: (2, None))
    observed: dict[str, object] = {}

    class ExecCalled(Exception):
        pass

    def _execv(_executable: str, command: list[str]) -> None:
        observed["command"] = command
        observed["request"] = runner.os.environ.get(runner.RECORD_ENV)
        raise ExecCalled

    monkeypatch.setattr(runner.os, "execv", _execv)

    with pytest.raises(ExecCalled):
        runner.main(["fast"])

    assert runner.HEALTH_PLUGIN_MODULE not in observed["command"]
    assert observed["request"] is None
    assert not health_store(tmp_path).exists()
