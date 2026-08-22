"""Sandboxed `%if` admission runtime and coordinator recovery."""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_condition_runtime import (
    evaluate_launch_condition,
    recover_launch_condition,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import (
    classify_condition_status,
    sanitize_condition_inputs,
)
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchConditionWire,
    LaunchPlanWire,
    LaunchUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
)
from sase.xprompt.code_value import make_code_value


def _agent_result(tmp_path: Path, name: str = "reviewer") -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=321,
        workspace_num=2,
        workspace_dir=str(tmp_path / "ws"),
        output_path=str(tmp_path / "out.log"),
        agent_name=name,
    )


def _plan(*units: LaunchUnitWire) -> LaunchPlanWire:
    return LaunchPlanWire(
        schema_version=1,
        launch_kind="multi_prompt",
        selected_project="sase",
        content_digest="d" * 64,
        units=list(units),
        approval_preview=["LaunchPlan v1"],
    )


def _run_plan(tmp_path: Path, plan: LaunchPlanWire, **kwargs: Any) -> Any:
    response_dir = tmp_path / "bundle"
    response_dir.mkdir(exist_ok=True)
    result = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-cond",
            "typed_plan": agent_launch_wire_to_json_dict(plan),
            "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
            "safe_inputs": {"task": "review", "api_token": "secret"},
        },
        spawn_coordinator=False,
        **kwargs,
    )
    return result, response_dir


def _condition(source: str, language: str = "bash") -> LaunchConditionWire:
    return LaunchConditionWire(
        code=make_code_value(source, language, language),
        context_fields=[
            "logical_unit",
            "selected_project",
            "safe_inputs",
            "waited_outcomes",
        ],
    )


def _conditioned_unit(
    logical_id: str,
    source: str,
    *,
    language: str = "bash",
    source_order: int = 0,
    prompt: str = "Do work",
) -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id=logical_id,
        source_order=source_order,
        payload=AgentUnitWire(
            prompt=prompt, identity="reviewer", identity_explicit=True
        ),
        condition=_condition(source, language),
    )


def test_classify_condition_status_matches_contract() -> None:
    pytest.importorskip("sase_core_rs")
    assert classify_condition_status(exit_code=0) == "eligible"
    assert classify_condition_status(exit_code=1) == "skipped"
    assert classify_condition_status(exit_code=2) == "condition_error"
    assert classify_condition_status(signal=9) == "condition_error"
    assert classify_condition_status(timed_out=True) == "condition_error"
    assert classify_condition_status(exit_code=0, cancelled=True) == "condition_error"


def test_sanitize_condition_inputs_drops_secrets() -> None:
    pytest.importorskip("sase_core_rs")
    assert sanitize_condition_inputs(
        {"task": "review", "api_token": "nope", "nested": {"password": "x", "ok": 1}}
    ) == {"task": "review", "nested": {"ok": 1}}


def test_bash_and_python_exit_classes_and_cleanup(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    eligible = _conditioned_unit("unit-1", "exit 0")
    skipped = _conditioned_unit("unit-1", "exit 1")
    errored = _conditioned_unit("unit-1", "raise SystemExit(2)", language="python")

    work = tmp_path / "eligible"
    verdict, message = evaluate_launch_condition(
        eligible,
        [],
        {
            "work_dir": str(work),
            "source_cwd": str(tmp_path),
            "supervise": False,
            "selected_project": "sase",
        },
    )
    assert verdict == "eligible"
    assert message is None
    assert (work / "result.json").is_file()
    assert stat.S_IMODE((work / "result.json").stat().st_mode) == 0o600
    assert not (work / "script.sh").exists()
    assert not (work / "context.json").exists()

    verdict, message = evaluate_launch_condition(
        skipped,
        [],
        {
            "work_dir": str(tmp_path / "skipped"),
            "source_cwd": str(tmp_path),
            "supervise": False,
        },
    )
    assert verdict == "skipped"
    assert message == "predicate exited 1"

    verdict, message = evaluate_launch_condition(
        errored,
        [],
        {
            "work_dir": str(tmp_path / "error"),
            "source_cwd": str(tmp_path),
            "supervise": False,
        },
    )
    assert verdict == "condition_error"
    assert message == "predicate exited 2"


def test_context_file_and_sanitized_environment(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    source = (
        "import json, os, sys\n"
        "payload = json.load(open(os.environ['SASE_CONDITION_CONTEXT'], encoding='utf-8'))\n"
        "assert payload['logical_unit']['logical_id'] == 'unit-1'\n"
        "assert payload['safe_inputs']['task'] == 'review'\n"
        "assert 'api_token' not in payload['safe_inputs']\n"
        "assert 'SASE_AGENT' not in os.environ\n"
        "assert 'AWS_SECRET_ACCESS_KEY' not in os.environ\n"
        "raise SystemExit(0)\n"
    )
    unit = _conditioned_unit("unit-1", source, language="python")
    os.environ["SASE_AGENT"] = "should-not-leak"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "should-not-leak"
    try:
        verdict, _message = evaluate_launch_condition(
            unit,
            [
                {
                    "target": {"kind": "logical", "logical_id": "unit-0"},
                    "outcome": "skipped",
                    "message": "predicate exited 1",
                }
            ],
            {
                "work_dir": str(tmp_path / "ctx"),
                "source_cwd": str(tmp_path),
                "supervise": False,
                "selected_project": "sase",
                "safe_inputs": {"task": "review", "api_token": "secret"},
            },
        )
    finally:
        os.environ.pop("SASE_AGENT", None)
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)
    assert verdict == "eligible"


def test_timeout_missing_cwd_and_missing_interpreter(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    sleepy = _conditioned_unit("unit-1", "sleep 30")
    ready = _conditioned_unit("unit-1", "exit 0")
    verdict, message = evaluate_launch_condition(
        sleepy,
        [],
        {
            "work_dir": str(tmp_path / "timeout"),
            "source_cwd": str(tmp_path),
            "supervise": False,
            "timeout_seconds": 0.2,
        },
    )
    assert verdict == "condition_error"
    assert message is not None and "timed out" in message

    verdict, message = evaluate_launch_condition(
        ready,
        [],
        {
            "work_dir": str(tmp_path / "cwd"),
            "source_cwd": str(tmp_path / "missing-cwd"),
            "supervise": False,
        },
    )
    assert verdict == "condition_error"
    assert message is not None and "cwd does not exist" in message

    py_unit = _conditioned_unit("unit-1", "raise SystemExit(0)", language="python")
    verdict, message = evaluate_launch_condition(
        py_unit,
        [],
        {
            "work_dir": str(tmp_path / "interp-py"),
            "source_cwd": str(tmp_path),
            "supervise": False,
            "python_executable": "/nonexistent/sase-python",
        },
    )
    assert verdict == "condition_error"
    assert message is not None and "missing condition interpreter" in message


def test_skip_does_not_dispatch_or_claim_resources(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    plan = _plan(
        _conditioned_unit("unit-1", "exit 1"),
        LaunchUnitWire(
            logical_id="unit-2",
            source_order=1,
            payload=AgentUnitWire(
                prompt="Follow up", identity="follow", identity_explicit=True
            ),
            waits=[WaitTargetWire(kind="logical", logical_id="unit-1", source="%wait")],
        ),
    )
    dispatched: list[str] = []

    def dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str, str | None, list[AgentLaunchResult]]:
        dispatched.append(unit.logical_id)
        return True, unit.logical_id, None, [_agent_result(tmp_path, unit.logical_id)]

    with pytest.MonkeyPatch.context() as monkeypatch:
        from unittest.mock import patch

        with (
            patch("sase.running_field.claim_workspace") as claim_workspace,
            patch("sase.procs.store.reserve_proc") as reserve_proc,
        ):
            monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
            progress, response_dir = _run_plan(
                tmp_path,
                plan,
                agent_dispatcher=dispatcher,
            )
    assert progress.summary is not None
    assert progress.summary.skipped == 1
    assert progress.summary.launched == 1
    assert dispatched == ["unit-2"]
    claim_workspace.assert_not_called()
    reserve_proc.assert_not_called()
    journal = (response_dir / "launch_admission" / "journal.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"phase": "skipped"' in journal
    assert (
        response_dir / "launch_admission" / "units" / "unit-1" / "result.json"
    ).is_file()


def test_proven_result_is_recovered_without_rerun(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    plan = _plan(_conditioned_unit("unit-1", "exit 0"))
    response_dir = tmp_path / "bundle"
    work = response_dir / "launch_admission" / "units" / "unit-1"
    work.mkdir(parents=True)
    (response_dir / "launch_admission").mkdir(parents=True, exist_ok=True)
    (response_dir / "launch_admission" / "journal.jsonl").write_text(
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
    (work / "result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "verdict": "eligible",
                "timed_out": False,
                "truncated": False,
                "cancelled": False,
                "code_digest": plan.units[0].condition.code.digest,
                "context_digest": "c" * 64,
                "message": None,
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []
    progress = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-recover",
            "typed_plan": agent_launch_wire_to_json_dict(plan),
            "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        condition_evaluator=lambda unit, waited, context: (
            calls.append("ran") or ("eligible", None)
        ),
        agent_dispatcher=lambda unit, fingerprint: (
            True,
            "reviewer",
            None,
            [_agent_result(tmp_path)],
        ),
    )
    assert calls == []
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.summary.condition_errors == 0


def test_live_pid_recovery_waits_for_result_file(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    import subprocess
    import sys

    work = tmp_path / "live"
    work.mkdir()
    result_path = work / "result.json"
    script = (
        "import json, time, pathlib\n"
        "time.sleep(0.2)\n"
        f"pathlib.Path({str(result_path)!r}).write_text("
        "json.dumps({"
        "'schema_version': 1, 'verdict': 'skipped', 'timed_out': False, "
        "'truncated': False, 'cancelled': False, 'code_digest': 'a' * 64, "
        "'context_digest': 'b' * 64, 'message': 'predicate exited 1'"
        "}), encoding='utf-8')\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (work / "check.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "logical_id": "unit-1",
                "pid": child.pid,
                "pgid": child.pid,
                "code_digest": "a" * 64,
                "context_digest": "b" * 64,
                "started_at_unix": time.time(),
            }
        ),
        encoding="utf-8",
    )
    try:
        recovered = recover_launch_condition(work, timeout_seconds=2.0)
        child.wait(timeout=2.0)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2.0)
    assert recovered == ("skipped", "predicate exited 1")


def test_literal_percent_and_substitution_stay_in_source(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    body = 'printf "%s" "%wait $(echo leaked)"; echo >&2; exit 0'
    unit = _conditioned_unit("unit-1", body)
    assert "%wait" in unit.condition.code.source  # type: ignore[union-attr]
    verdict, _message = evaluate_launch_condition(
        unit,
        [],
        {
            "work_dir": str(tmp_path / "literal"),
            "source_cwd": str(tmp_path),
            "supervise": False,
        },
    )
    assert verdict == "eligible"


def test_coordinator_condition_error_does_not_block_independent_unit(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    plan = _plan(
        _conditioned_unit("unit-1", "exit 2"),
        LaunchUnitWire(
            logical_id="unit-2",
            source_order=1,
            payload=AgentUnitWire(prompt="Independent", identity="other"),
        ),
    )
    dispatched: list[str] = []
    progress, _ = _run_plan(
        tmp_path,
        plan,
        agent_dispatcher=lambda unit, fingerprint: (
            dispatched.append(unit.logical_id)
            or (True, unit.logical_id, None, [_agent_result(tmp_path, unit.logical_id)])
        ),
    )
    assert progress.summary is not None
    assert progress.summary.condition_errors == 1
    assert progress.summary.launched == 1
    assert dispatched == ["unit-2"]
