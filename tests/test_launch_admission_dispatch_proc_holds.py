"""Launch-admission proc hold gating and typed hold pre-arm behavior."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_request_types import LaunchRequestError
from sase.core.agent_hold_facade import (
    arm_agent_hold,
    list_agent_holds_without_liveness,
    release_agent_hold,
)
from sase.core.agent_launch_wire import (
    HoldFieldsWire,
    WaitTargetWire,
)
from sase.feature_flags import override_flags
from tests._launch_admission_helpers import (
    agent_unit as _agent_unit,
    plan as _plan,
    proc_unit as _proc_unit,
    run_plan as _run_plan,
)


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


def test_typed_hold_prearm_ignores_retired_flag_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    with override_flags(agent_holds=False):
        blocked, response_dir = _run_plan(
            tmp_path,
            _plan(
                _agent_unit(
                    "unit-1",
                    waits=[WaitTargetWire(kind="time", value="1h")],
                    hold=HoldFieldsWire(future=True),
                )
            ),
            request_id="req-hold-flag-off",
        )

    marker = response_dir / "launch_admission" / "units" / "unit-1.hold.json"
    assert blocked.admission_complete is False
    assert marker.exists()
    holds = list_agent_holds_without_liveness()
    assert len(holds) == 1
    assert holds[0]["selectors"]["future"] is True


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
