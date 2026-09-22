"""Launch-admission hold lifecycle around agent and proc dispatch."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launch_admission import (
    dispatch_typed_launch_request,
    run_coordinator_in_bundle,
)
from sase.agent.launch_hold import LAUNCH_HOLD_KEY_ENV
from sase.agent.launch_request_response import REQUEST_FILENAME
from sase.agent.launch_types import AgentLaunchResult
from sase.agent.proc_capacity_admission import evaluate_proc_capacity_admission
from sase.core.agent_hold_facade import list_agent_holds_without_liveness
from sase.core.agent_launch_wire import (
    HoldFieldsWire,
    LaunchConditionWire,
    LaunchUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
)
from sase.core.runner_slots import HOLD_ARMER_WAIT_PRIORITY
from sase.feature_flags import override_flags
from tests._launch_admission_helpers import (
    agent_unit as _agent_unit,
    code as _code,
    plan as _plan,
    proc_unit as _proc_unit,
    run_plan as _run_plan,
)


def _write_launch_request(response_dir: Path, data: dict[str, object]) -> None:
    (response_dir / REQUEST_FILENAME).write_text(
        json.dumps({"kind": "launch", "payload": data}),
        encoding="utf-8",
    )


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
