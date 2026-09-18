"""Launch-admission agent dispatch behavior."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_admission import (
    dispatch_typed_launch_request,
    run_coordinator_in_bundle,
)
from sase.agent.launch_hold import LAUNCH_HOLD_KEY_ENV
from sase.agent.launch_request_response import REQUEST_FILENAME
from sase.agent.launch_request_types import LaunchRequestError
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.proc_capacity_admission import evaluate_proc_capacity_admission
from sase.core.agent_hold_facade import (
    arm_agent_hold,
    list_agent_holds_without_liveness,
    release_agent_hold,
)
from sase.core.agent_launch_wire import (
    HoldFieldsWire,
    LaunchConditionWire,
    LaunchUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
)
from sase.core.runner_slots import HOLD_ARMER_WAIT_PRIORITY
from sase.axe import run_agent_wait_slots
from sase.feature_flags import override_flags
from tests._launch_admission_helpers import (
    agent_unit as _agent_unit,
    agent_result as _agent_result,
    code as _code,
    plan as _plan,
    proc_unit as _proc_unit,
    run_plan as _run_plan,
)
from tests._runner_slot_fixtures import artifact as _artifact
from tests._runner_slot_fixtures import record as _record


def _write_launch_request(response_dir: Path, data: dict[str, object]) -> None:
    (response_dir / REQUEST_FILENAME).write_text(
        json.dumps({"kind": "launch", "payload": data}),
        encoding="utf-8",
    )


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


def test_typed_hold_prearm_is_idempotent_while_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    unit = _agent_unit(
        "unit-1",
        waits=[WaitTargetWire(kind="time", value="1h")],
        hold=HoldFieldsWire(future=True),
    )
    launch_plan = _plan(unit)

    with override_flags():
        blocked, response_dir = _run_plan(
            tmp_path,
            launch_plan,
            request_id="req-hold-idempotent",
        )
        first = list_agent_holds_without_liveness()[0]
        replay, _ = _run_plan(
            tmp_path,
            launch_plan,
            request_id="req-hold-idempotent",
        )
        second = list_agent_holds_without_liveness()[0]

    marker = response_dir / "launch_admission" / "units" / "unit-1.hold.json"
    assert blocked.admission_complete is False
    assert replay.admission_complete is False
    assert marker.is_file()
    assert first["created_at"] == second["created_at"]
    assert [hold["armer"]["key"] for hold in list_agent_holds_without_liveness()] == [
        "launch:req-hold-idempotent/unit-1"
    ]


def test_typed_hold_prearm_records_agent_and_proc_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    pending_dir = str(tmp_path / "pending-agent")
    launch_plan = _plan(
        _agent_unit(
            "unit-agent",
            waits=[WaitTargetWire(kind="time", value="1h")],
            hold=HoldFieldsWire(pending=True, scope="host", ttl_seconds=60),
        ),
        _proc_unit(
            "unit-proc",
            tmp_path,
            source_order=1,
            waits=[WaitTargetWire(kind="time", value="1h")],
            hold=HoldFieldsWire(future=True, scope="project", ttl_seconds=90),
        ),
    )

    with (
        override_flags(),
        patch(
            "sase.integrations.agent_list_entries.agent_list_entries",
            return_value=[SimpleNamespace(status="WAITING", artifacts_dir=pending_dir)],
        ),
    ):
        blocked, response_dir = _run_plan(
            tmp_path,
            launch_plan,
            request_id="req-hold-fields",
        )

    assert blocked.admission_complete is False
    holds = {
        str(hold["armer"]["key"]): hold for hold in list_agent_holds_without_liveness()
    }
    agent_hold = holds["launch:req-hold-fields/unit-agent"]
    proc_hold = holds["launch:req-hold-fields/unit-proc"]
    assert agent_hold["armer"]["kind"] == "launch"
    assert agent_hold["armer"]["agent_name"] == "reviewer"
    assert agent_hold["armer"]["project"] == "sase"
    assert agent_hold["armer"]["done_marker_path"] == str(
        response_dir / "launch_admission" / "receipt.json"
    )
    assert pending_dir in agent_hold["selectors"]["artifact_dirs"]
    assert "host" in str(agent_hold["scope"]).lower()
    assert agent_hold["expires_at"] is not None
    assert proc_hold["armer"]["kind"] == "launch"
    assert proc_hold["armer"]["agent_name"] is None
    assert proc_hold["armer"]["project"] == "sase"
    assert proc_hold["selectors"]["future"] is True
    assert "project" in str(proc_hold["scope"]).lower()


def test_typed_hold_prearm_rejects_empty_request_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with override_flags():
        with pytest.raises(LaunchRequestError, match="request_id"):
            _run_plan(
                tmp_path,
                _plan(_agent_unit("unit-1", hold=HoldFieldsWire(future=True))),
                request_id="",
            )

    assert list_agent_holds_without_liveness() == []


def test_typed_hold_prearm_failure_rolls_back_already_armed_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    first = _agent_unit("unit-1", hold=HoldFieldsWire(future=True))
    second = _agent_unit(
        "unit-2",
        source_order=1,
        hold=HoldFieldsWire(names=["reviewer"]),
    )

    with override_flags():
        with pytest.raises(LaunchRequestError, match="%hold:"):
            _run_plan(
                tmp_path,
                _plan(first, second),
                request_id="req-hold-rollback",
            )

    units_dir = tmp_path / "bundle" / "launch_admission" / "units"
    assert not (units_dir / "unit-1.hold.json").exists()
    assert not (units_dir / "unit-2.hold.json").exists()
    assert list_agent_holds_without_liveness() == []


def test_typed_hold_prearm_ttl_failure_rolls_back_already_armed_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    first = _agent_unit(
        "unit-1",
        waits=[WaitTargetWire(kind="time", value="1h")],
        hold=HoldFieldsWire(future=True, ttl_seconds=1),
    )
    second = _agent_unit(
        "unit-2",
        source_order=1,
        waits=[WaitTargetWire(kind="time", value="1h")],
        hold=HoldFieldsWire(future=True, ttl_seconds=2),
    )

    with (
        override_flags(),
        patch("sase.config.core.get_agent_hold_max_ttl_seconds", return_value=1.0),
    ):
        with pytest.raises(LaunchRequestError, match="%hold:"):
            _run_plan(
                tmp_path,
                _plan(first, second),
                request_id="req-hold-ttl-rollback",
            )

    units_dir = tmp_path / "bundle" / "launch_admission" / "units"
    assert not (units_dir / "unit-1.hold.json").exists()
    assert not (units_dir / "unit-2.hold.json").exists()
    assert list_agent_holds_without_liveness() == []


def test_agent_dispatch_carries_hold_key_and_reanchors_to_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    captured_env: dict[str, str] = {}
    artifacts_dir = tmp_path / "runner-artifacts"
    artifacts_dir.mkdir()

    def launch(prompt: str, *, extra_env: dict[str, str]) -> list[AgentLaunchResult]:
        del prompt
        captured_env.update(extra_env)
        return [
            AgentLaunchResult(
                pid=os.getpid(),
                workspace_num=1,
                workspace_dir=str(tmp_path / "ws"),
                output_path=str(tmp_path / "out.log"),
                artifacts_dir=str(artifacts_dir),
                agent_name="reviewer",
            )
        ]

    with (
        override_flags(),
        patch("sase.agent.launcher.launch_agents_from_cwd", side_effect=launch),
    ):
        progress, _ = _run_plan(
            tmp_path,
            _plan(_agent_unit("unit-1", hold=HoldFieldsWire(future=True))),
            request_id="req-hold-env",
        )

    holds = list_agent_holds_without_liveness()
    assert progress.admission_complete is True
    assert captured_env[LAUNCH_HOLD_KEY_ENV] == "launch:req-hold-env/unit-1"
    assert len(holds) == 1
    assert holds[0]["armer"]["key"] == "launch:req-hold-env/unit-1"
    assert holds[0]["armer"]["done_marker_path"] == str(artifacts_dir / "done.json")


@pytest.mark.parametrize("failure", ["lookup", "rebind"])
def test_agent_dispatch_reanchor_failure_still_records_launched_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = tmp_path / "runner-artifacts"
    artifacts_dir.mkdir()
    spawned = AgentLaunchResult(
        pid=os.getpid(),
        workspace_num=1,
        workspace_dir=str(tmp_path / "ws"),
        output_path=str(tmp_path / "out.log"),
        artifacts_dir=str(artifacts_dir),
        agent_name="reviewer",
    )
    patches = [
        patch(
            "sase.agent.launch_hold._hold_record_without_liveness",
            side_effect=RuntimeError("raw store lookup failed"),
        )
    ]
    if failure == "rebind":
        patches = [
            patch(
                "sase.agent.launch_hold.rebind_hold",
                side_effect=RuntimeError("rebind failed"),
            )
        ]

    with override_flags(), caplog.at_level("WARNING"):
        with patches[0]:
            progress, response_dir = _run_plan(
                tmp_path,
                _plan(_agent_unit("unit-1", hold=HoldFieldsWire(future=True))),
                request_id=f"req-hold-{failure}-best-effort",
                agent_dispatcher=lambda unit, fingerprint: (
                    True,
                    "reviewer",
                    None,
                    [spawned],
                ),
            )

    receipt = response_dir / "launch_admission" / "units" / "unit-1.json"
    assert progress.admission_complete is True
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert receipt.is_file()
    assert "launch hold runner re-anchor failed for unit unit-1" in caplog.text


@pytest.mark.parametrize("failure", ["lookup", "rebind"])
def test_coordinator_reanchor_failure_still_writes_started_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    response_dir = tmp_path / "bundle"
    response_dir.mkdir()
    launch_plan = _plan(
        _agent_unit(
            "unit-1",
            waits=[WaitTargetWire(kind="time", value="1h")],
            hold=HoldFieldsWire(future=True),
        )
    )
    request_id = f"req-coordinator-{failure}-best-effort"
    data = {
        "request_id": request_id,
        "typed_plan": agent_launch_wire_to_json_dict(launch_plan),
        "dispatch": {"cwd": str(tmp_path), "prompt": "%wait(time=1h)\nDo work"},
    }

    with override_flags():
        first = dispatch_typed_launch_request(
            response_dir,
            data,
            spawn_coordinator=False,
        )
    assert first.admission_complete is False
    _write_launch_request(response_dir, data)

    patches = [
        patch(
            "sase.agent.launch_hold._hold_record_without_liveness",
            side_effect=RuntimeError("raw store lookup failed"),
        )
    ]
    if failure == "rebind":
        patches = [
            patch(
                "sase.agent.launch_hold.rebind_hold",
                side_effect=RuntimeError("rebind failed"),
            )
        ]

    with caplog.at_level("WARNING"):
        with patches[0]:
            progress = run_coordinator_in_bundle(response_dir, cancelled=lambda: True)

    started = response_dir / "launch_admission" / "started.json"
    assert started.is_file()
    assert progress.complete is True
    assert "launch hold coordinator re-anchor failed for unit unit-1" in caplog.text


def test_launch_hold_releases_when_unit_never_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with override_flags():
        progress, _ = _run_plan(
            tmp_path,
            _plan(_agent_unit("unit-1", hold=HoldFieldsWire(future=True))),
            request_id="req-hold-release",
            agent_dispatcher=lambda unit, fingerprint: (
                False,
                None,
                "spawn failed",
                [],
            ),
        )

    assert progress.admission_complete is True
    assert progress.summary is not None
    assert progress.summary.launch_errors == 1
    assert list_agent_holds_without_liveness() == []


@pytest.mark.parametrize("phase", ["skipped", "condition_error"])
def test_launch_hold_releases_when_condition_prevents_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def condition(
        unit: LaunchUnitWire,
        waited_outcomes: list[dict[str, object]],
        context: dict[str, object],
    ) -> tuple[str, str]:
        del unit, waited_outcomes, context
        return phase, "condition stopped dispatch"

    with override_flags():
        progress, _ = _run_plan(
            tmp_path,
            _plan(
                _agent_unit(
                    "unit-1",
                    condition=LaunchConditionWire(code=_code()),
                    hold=HoldFieldsWire(future=True),
                )
            ),
            request_id=f"req-hold-{phase}",
            condition_evaluator=condition,
        )

    assert progress.admission_complete is True
    assert list_agent_holds_without_liveness() == []


def test_launch_hold_releases_when_admission_is_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with override_flags():
        progress, _ = _run_plan(
            tmp_path,
            _plan(_agent_unit("unit-1", hold=HoldFieldsWire(future=True))),
            request_id="req-hold-cancelled",
            cancelled=lambda: True,
        )

    assert progress.admission_complete is True
    assert list_agent_holds_without_liveness() == []


def test_hold_carrying_proc_does_not_block_on_its_own_future_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    dispatched: list[str] = []

    with override_flags():
        progress, _ = _run_plan(
            tmp_path,
            _plan(
                _proc_unit(
                    "unit-1",
                    tmp_path,
                    hold=HoldFieldsWire(future=True),
                )
            ),
            request_id="req-proc-self-hold",
            proc_dispatcher=lambda unit, fingerprint: (
                dispatched.append(fingerprint) or (True, "proc-self", None, [])
            ),
        )

    assert progress.admission_complete is True
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert len(dispatched) == 1


def test_hold_carrying_proc_queue_uses_implied_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    captured: dict[str, object] = {}
    unit = _proc_unit(
        "unit-1",
        tmp_path,
        queue_capacity=1,
        hold=HoldFieldsWire(future=True),
    )

    def snapshot(*args: object, **kwargs: object) -> dict[str, object]:
        del args
        captured["candidate"] = kwargs["candidate"]
        return {}

    with (
        patch(
            "sase.agent.proc_capacity_admission.runner_capacity_snapshot",
            side_effect=snapshot,
        ),
        patch(
            "sase.axe.run_agent_wait_slot_candidate.require_candidate_decision",
            return_value={"decision": "acquire_capacity", "blockers": []},
        ),
        patch("sase.config.core.get_max_running_agents", return_value=1),
    ):
        decision = evaluate_proc_capacity_admission(
            unit,
            admission_dir=tmp_path / "admission",
            request_id="req-proc-priority",
            selected_project="sase",
            requested_at="2026-09-17T00:00:00+00:00",
            eligible_since=None,
            now=datetime.fromisoformat("2026-09-17T00:00:00+00:00"),
        )

    assert decision.admitted is True
    candidate = captured["candidate"]
    assert isinstance(candidate, dict)
    assert candidate["wait_priority"] == HOLD_ARMER_WAIT_PRIORITY


def test_hold_carrying_proc_preserves_authored_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    captured: dict[str, object] = {}
    unit = _proc_unit(
        "unit-1",
        tmp_path,
        queue_capacity=1,
        wait_priority=7,
        hold=HoldFieldsWire(future=True),
    )

    def snapshot(*args: object, **kwargs: object) -> dict[str, object]:
        del args
        captured["candidate"] = kwargs["candidate"]
        return {}

    with (
        patch(
            "sase.agent.proc_capacity_admission.runner_capacity_snapshot",
            side_effect=snapshot,
        ),
        patch(
            "sase.axe.run_agent_wait_slot_candidate.require_candidate_decision",
            return_value={"decision": "acquire_capacity", "blockers": []},
        ),
        patch("sase.config.core.get_max_running_agents", return_value=1),
    ):
        decision = evaluate_proc_capacity_admission(
            unit,
            admission_dir=tmp_path / "admission",
            request_id="req-proc-authored-priority",
            selected_project="sase",
            requested_at="2026-09-17T00:00:00+00:00",
            eligible_since=None,
            now=datetime.fromisoformat("2026-09-17T00:00:00+00:00"),
        )

    assert decision.admitted is True
    candidate = captured["candidate"]
    assert isinstance(candidate, dict)
    assert candidate["wait_priority"] == 7
