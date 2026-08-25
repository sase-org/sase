"""Launch-admission condition and replay failure handling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchConditionWire,
    LaunchUnitWire,
    agent_launch_wire_to_json_dict,
)
from tests._launch_admission_helpers import (
    agent_result as _agent_result,
    agent_unit as _agent_unit,
    code as _code,
    plan as _plan,
    run_plan as _run_plan,
)


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
