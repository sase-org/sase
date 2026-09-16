"""Launch-admission agent dispatch behavior."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_hold_facade import arm_agent_hold, release_agent_hold
from sase.core.agent_launch_wire import LaunchUnitWire
from sase.axe import run_agent_wait_slots
from tests._launch_admission_helpers import (
    agent_result as _agent_result,
    agent_unit as _agent_unit,
    plan as _plan,
    proc_unit as _proc_unit,
    run_plan as _run_plan,
)
from tests._runner_slot_fixtures import artifact as _artifact
from tests._runner_slot_fixtures import record as _record


def test_engine_dispatches_agent_after_empty_wait(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    dispatched: list[str] = []

    def dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str, str | None, list[AgentLaunchResult]]:
        dispatched.append(fingerprint)
        return True, "reviewer", None, [_agent_result(tmp_path)]

    progress, _response_dir = _run_plan(
        tmp_path,
        _plan(_agent_unit("unit-1")),
        request_id="req-1",
        agent_dispatcher=dispatcher,
        proc_dispatcher=lambda unit, fingerprint: (False, None, "unused", []),
    )
    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.summary.launch_errors == 0
    assert len(dispatched) == 1
    replay, _ = _run_plan(
        tmp_path,
        _plan(_agent_unit("unit-1")),
        request_id="req-1",
        agent_dispatcher=dispatcher,
    )
    assert replay.summary is not None
    assert replay.summary.launched == 1
    assert len(dispatched) == 1


def test_partial_success_keeps_launched_identity(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    identities: list[str] = []

    def dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        if unit.logical_id == "unit-2":
            return False, None, "spawn failed", []
        identities.append(unit.logical_id)
        return True, unit.logical_id, None, [_agent_result(tmp_path, unit.logical_id)]

    progress, _ = _run_plan(
        tmp_path,
        _plan(_agent_unit("unit-1"), _agent_unit("unit-2", source_order=1)),
        request_id="req-partial",
        agent_dispatcher=dispatcher,
    )
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.summary.launch_errors == 1
    assert identities == ["unit-1"]
    assert any(
        result.logical_id == "unit-1" and result.outcome == "launched"
        for result in progress.unit_results
    )


def test_cancel_open_units_does_not_erase_launched(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    cancelled = False

    def dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        nonlocal cancelled
        cancelled = True
        return True, "reviewer", None, [_agent_result(tmp_path)]

    progress, _ = _run_plan(
        tmp_path,
        _plan(_agent_unit("unit-1"), _agent_unit("unit-2", source_order=1)),
        request_id="req-cancel",
        cancelled=lambda: cancelled,
        agent_dispatcher=dispatcher,
    )
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.summary.launch_errors == 1
    outcomes = {result.logical_id: result.outcome for result in progress.unit_results}
    assert outcomes["unit-1"] == "launched"
    assert outcomes["unit-2"] == "launch_error"


def test_proc_queue_capacity_blocks_then_dispatches_when_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    running = _artifact(
        tmp_path,
        "20260916010101",
        100,
        queue_weight=1.0,
        queue_weight_explicit=True,
    )
    occupied = True
    dispatched: list[str] = []

    def scan() -> list[object]:
        return [_record(running, started=True)] if occupied else []

    def proc_dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str, str | None, list[AgentLaunchResult]]:
        dispatched.append(fingerprint)
        return True, "proc-1", None, []

    launch_plan = _plan(
        _proc_unit(
            "unit-1",
            tmp_path,
            queue_capacity=1,
            queue_weight=0.0,
            queue_weight_explicit=False,
        )
    )
    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch("sase.config.core.get_max_running_agents", return_value=1),
    ):
        blocked, response_dir = _run_plan(
            tmp_path,
            launch_plan,
            request_id="req-proc-queue",
            proc_dispatcher=proc_dispatcher,
        )
        assert blocked.admission_complete is False
        assert dispatched == []
        assert blocked.unit_results[0].outcome == "eligible"
        assert "capacity" in str(blocked.unit_results[0].message)

        occupied = False
        admitted, _ = _run_plan(
            tmp_path,
            launch_plan,
            request_id="req-proc-queue",
            proc_dispatcher=proc_dispatcher,
        )

    assert response_dir == tmp_path / "bundle"
    assert admitted.admission_complete is True
    assert admitted.summary is not None
    assert admitted.summary.launched == 1
    assert len(dispatched) == 1
    assert admitted.unit_results[0].outcome == "launched"
    assert admitted.unit_results[0].message in (None, "")


def test_authored_proc_weight_blocks_when_it_cannot_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    dispatched: list[str] = []

    launch_plan = _plan(
        _proc_unit(
            "unit-1",
            tmp_path,
            queue_weight=2.0,
            queue_weight_explicit=True,
        )
    )
    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch("sase.config.core.get_max_running_agents", return_value=1),
    ):
        progress, _ = _run_plan(
            tmp_path,
            launch_plan,
            request_id="req-proc-heavy",
            proc_dispatcher=lambda unit, fingerprint: (
                dispatched.append(fingerprint) or (True, "proc-heavy", None, [])
            ),
        )

    assert dispatched == []
    assert progress.admission_complete is False
    assert progress.summary is not None
    assert progress.summary.launch_errors == 0
    assert progress.unit_results[0].outcome == "eligible"
    assert "capacity" in str(progress.unit_results[0].message)


def test_agent_hold_named_proc_shell_blocks_until_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.core.agent_hold_facade._project_for_cwd", lambda: "sase")
    hold = arm_agent_hold(
        names=["checks"],
        scope="host",
        ttl_seconds=60.0,
        pid_override=os.getpid(),
    )
    dispatched: list[str] = []
    launch_plan = _plan(_proc_unit("unit-1", tmp_path, shell_name="checks"))

    blocked, response_dir = _run_plan(
        tmp_path,
        launch_plan,
        request_id="req-proc-hold",
        proc_dispatcher=lambda unit, fingerprint: (
            dispatched.append(fingerprint) or (True, "proc-1", None, [])
        ),
    )

    assert blocked.admission_complete is False
    assert blocked.summary is not None
    assert blocked.summary.launched == 0
    assert dispatched == []

    assert release_agent_hold(hold.record["armer"]["key"])
    admitted, replay_response_dir = _run_plan(
        tmp_path,
        launch_plan,
        request_id="req-proc-hold",
        proc_dispatcher=lambda unit, fingerprint: (
            dispatched.append(fingerprint) or (True, "proc-1", None, [])
        ),
    )

    assert replay_response_dir == response_dir
    assert admitted.admission_complete is True
    assert admitted.summary is not None
    assert admitted.summary.launched == 1
    assert len(dispatched) == 1


def test_agent_hold_future_blocks_proc_submitted_after_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.core.agent_hold_facade._project_for_cwd", lambda: "sase")
    arm_agent_hold(
        future=True,
        scope="host",
        ttl_seconds=60.0,
        pid_override=os.getpid(),
    )
    dispatched: list[str] = []

    blocked, _ = _run_plan(
        tmp_path,
        _plan(_proc_unit("unit-1", tmp_path)),
        request_id="req-proc-future-hold",
        proc_dispatcher=lambda unit, fingerprint: (
            dispatched.append(fingerprint) or (True, "proc-1", None, [])
        ),
    )

    assert blocked.admission_complete is False
    assert blocked.summary is not None
    assert blocked.summary.launched == 0
    assert dispatched == []


def test_agent_hold_does_not_retouch_dispatched_proc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.core.agent_hold_facade._project_for_cwd", lambda: "sase")
    dispatched: list[str] = []
    launch_plan = _plan(_proc_unit("unit-1", tmp_path, shell_name="checks"))

    first, _ = _run_plan(
        tmp_path,
        launch_plan,
        request_id="req-proc-dispatched-hold",
        proc_dispatcher=lambda unit, fingerprint: (
            dispatched.append(fingerprint) or (True, "proc-1", None, [])
        ),
    )
    assert first.admission_complete is True
    assert len(dispatched) == 1

    arm_agent_hold(
        names=["checks"],
        scope="host",
        ttl_seconds=60.0,
        pid_override=os.getpid(),
    )
    replay, _ = _run_plan(
        tmp_path,
        launch_plan,
        request_id="req-proc-dispatched-hold",
        proc_dispatcher=lambda unit, fingerprint: (
            dispatched.append(fingerprint) or (True, "proc-1", None, [])
        ),
    )

    assert replay.admission_complete is True
    assert replay.summary is not None
    assert replay.summary.launched == 1
    assert len(dispatched) == 1
