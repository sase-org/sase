"""Durable launch-admission coordinator behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchConditionWire,
    LaunchPlanWire,
    LaunchUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
)
from tests._launch_admission_helpers import (
    agent_result as _agent_result,
    agent_unit as _agent_unit,
    code as _code,
    plan as _plan,
    run_plan as _run_plan,
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

    progress, response_dir = _run_plan(
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


def test_waiting_does_not_claim_resources(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    claims: list[str] = []

    def wait_resolver(
        plan: LaunchPlanWire,
        states: dict[str, dict[str, Any]],
        *,
        now: float,
        waiting_since: Any,
    ) -> list[dict[str, Any]]:
        del plan, states, now, waiting_since
        claims.append("wait")
        return [
            {
                "target": {"kind": "agent", "name": "builder"},
                "resolved": False,
            }
        ]

    with (
        patch("sase.running_field.claim_workspace") as claim_workspace,
        patch("sase.procs.store.reserve_proc") as reserve_proc,
    ):
        progress, _ = _run_plan(
            tmp_path,
            _plan(
                _agent_unit(
                    "unit-1",
                    waits=[WaitTargetWire(kind="agent", name="builder")],
                )
            ),
            request_id="req-wait",
            wait_resolver=wait_resolver,
            agent_dispatcher=lambda unit, fingerprint: (
                True,
                "x",
                None,
                [_agent_result(tmp_path)],
            ),
        )

    assert not progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.launched == 0
    assert claims
    claim_workspace.assert_not_called()
    reserve_proc.assert_not_called()


def test_skipped_predecessor_does_not_retarget(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")

    def evaluator(
        unit: LaunchUnitWire,
        waited: list[dict[str, Any]],
        context: Any,
    ) -> tuple[str, str | None]:
        del waited, context
        if unit.logical_id == "unit-1":
            return "skipped", "predicate exited 1"
        return "eligible", None

    progress, response_dir = _run_plan(
        tmp_path,
        _plan(
            LaunchUnitWire(
                logical_id="unit-1",
                source_order=0,
                payload=AgentUnitWire(prompt="First"),
                condition=LaunchConditionWire(code=_code()),
            ),
            _agent_unit(
                "unit-2",
                source_order=1,
                waits=[
                    WaitTargetWire(kind="logical", logical_id="unit-1", source="%wait")
                ],
            ),
        ),
        request_id="req-skip",
        condition_evaluator=evaluator,
        agent_dispatcher=lambda unit, fingerprint: (
            True,
            unit.logical_id,
            None,
            [_agent_result(tmp_path, unit.logical_id)],
        ),
    )
    assert progress.summary is not None
    assert progress.summary.skipped == 1
    assert progress.summary.launched == 1
    journal = (response_dir / "launch_admission" / "journal.jsonl").read_text(
        encoding="utf-8"
    )
    waited = None
    for line in journal.splitlines():
        entry = json.loads(line)
        if entry.get("logical_id") == "unit-2" and entry.get("waited_outcomes"):
            waited = entry["waited_outcomes"]
    assert waited is not None
    assert waited[0]["outcome"] == "skipped"
    assert waited[0]["target"]["logical_id"] == "unit-1"


def test_condition_error_is_not_generic_dispatch_failure(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")

    progress, _ = _run_plan(
        tmp_path,
        _plan(
            LaunchUnitWire(
                logical_id="unit-1",
                source_order=0,
                payload=AgentUnitWire(prompt="First"),
                condition=LaunchConditionWire(code=_code()),
            ),
            _agent_unit("unit-2", source_order=1),
        ),
        request_id="req-cond",
        condition_evaluator=lambda unit, waited, context: (
            "condition_error",
            "exit 2",
        ),
        agent_dispatcher=lambda unit, fingerprint: (
            True,
            unit.logical_id,
            None,
            [_agent_result(tmp_path, unit.logical_id)],
        ),
    )
    assert progress.summary is not None
    assert progress.summary.condition_errors == 1
    assert progress.summary.launched == 1
    assert progress.summary.launch_errors == 0


def test_checking_crash_does_not_rerun_predicate(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")

    plan = _plan(
        LaunchUnitWire(
            logical_id="unit-1",
            source_order=0,
            payload=AgentUnitWire(prompt="First"),
            condition=LaunchConditionWire(code=_code()),
        )
    )
    response_dir = tmp_path / "bundle"
    admission_dir = response_dir / "launch_admission"
    admission_dir.mkdir(parents=True)
    (admission_dir / "journal.jsonl").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "seq": 1,
                "logical_id": "unit-1",
                "phase": "checking",
                "recorded_at_unix": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[str] = []
    progress = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-crash-check",
            "typed_plan": agent_launch_wire_to_json_dict(plan),
        },
        spawn_coordinator=False,
        condition_evaluator=lambda unit, waited, context: (
            calls.append("ran") or ("eligible", None)
        ),
        agent_dispatcher=lambda unit, fingerprint: (
            True,
            "x",
            None,
            [_agent_result(tmp_path)],
        ),
    )
    assert calls == []
    assert progress.summary is not None
    assert progress.summary.condition_errors == 1
    assert progress.summary.launched == 0


def test_dispatch_crash_does_not_duplicate_spawn(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    response_dir = tmp_path / "bundle"
    admission_dir = response_dir / "launch_admission"
    admission_dir.mkdir(parents=True)
    (admission_dir / "journal.jsonl").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "seq": 1,
                "logical_id": "unit-1",
                "phase": "dispatching",
                "fingerprint": "fp",
                "recorded_at_unix": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[str] = []
    progress = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-crash-dispatch",
            "typed_plan": agent_launch_wire_to_json_dict(_plan(_agent_unit("unit-1"))),
        },
        spawn_coordinator=False,
        agent_dispatcher=lambda unit, fingerprint: (
            calls.append(fingerprint)
            or (True, "reviewer", None, [_agent_result(tmp_path)])
        ),
    )
    assert calls == []
    assert progress.summary is not None
    assert progress.summary.launch_errors == 1


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
