"""Durable launch-admission coordinator behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_preview import render_launch_preview_markdown
from sase.agent.launch_request import (
    create_launch_approval_request,
    stop_launch_admission,
)
from sase.agent.launch_request_response import dispatch_approved_launch_request
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchConditionWire,
    LaunchPlanWire,
    LaunchUnitWire,
    ProcUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
    launch_plan_from_dict,
)
from sase.core.agent_launch_facade import plan_typed_launch_units
from sase.feature_flags import override_flags
from sase.xprompt.code_value import CodeValue


def _agent_result(tmp_path: Path, name: str = "reviewer") -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=321,
        workspace_num=2,
        workspace_dir=str(tmp_path / "ws"),
        output_path=str(tmp_path / "out.log"),
        agent_name=name,
    )


def _code() -> CodeValue:
    return CodeValue(
        source="just check",
        language="bash",
        info_string=None,
        digest="b" * 64,
        preview="just check",
    )


def _run_plan(
    tmp_path: Path,
    plan: LaunchPlanWire,
    *,
    request_id: str = "req",
    **kwargs: Any,
) -> Any:
    response_dir = tmp_path / "bundle"
    response_dir.mkdir(exist_ok=True)
    result = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": request_id,
            "typed_plan": agent_launch_wire_to_json_dict(plan),
            "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        **kwargs,
    )
    return result, response_dir


def _plan(*units: LaunchUnitWire) -> LaunchPlanWire:
    return LaunchPlanWire(
        schema_version=1,
        launch_kind="multi_prompt",
        selected_project="sase",
        content_digest="d" * 64,
        units=list(units),
        approval_preview=["LaunchPlan v1"],
    )


def _agent_unit(
    logical_id: str,
    *,
    source_order: int = 0,
    waits: list[WaitTargetWire] | None = None,
    condition: Any = None,
) -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id=logical_id,
        source_order=source_order,
        payload=AgentUnitWire(
            prompt="Do work", identity="reviewer", identity_explicit=True
        ),
        waits=list(waits or []),
        condition=condition,
    )


def _proc_unit(
    logical_id: str,
    cwd: Path,
    *,
    source_order: int = 0,
    condition: Any = None,
) -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id=logical_id,
        source_order=source_order,
        payload=ProcUnitWire(
            code=_code(),
            workspace=False,
            cwd=str(cwd),
        ),
        condition=condition,
    )


def test_payload_json_includes_kind() -> None:
    plan = _plan(_agent_unit("unit-1"))
    payload = agent_launch_wire_to_json_dict(plan)
    assert payload["units"][0]["payload"]["kind"] == "agent"


def test_create_request_omits_typed_plan_when_flag_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    result = create_launch_approval_request(
        {"schema_version": 1, "prompt": "Do work", "reason": "cover flag off"}
    )
    written = json.loads(result.request_path.read_text(encoding="utf-8"))["payload"]
    assert "typed_plan" not in written


def test_create_request_attaches_typed_plan_when_flag_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    with override_flags(typed_launch_units=True):
        result = create_launch_approval_request(
            {"schema_version": 1, "prompt": "Do work", "reason": "cover flag on"}
        )
    written = json.loads(result.request_path.read_text(encoding="utf-8"))["payload"]
    assert written["typed_plan"]["units"][0]["payload"]["kind"] == "agent"
    assert written["plan_digest"] == written["typed_plan"]["content_digest"]
    preview = result.preview_path.read_text(encoding="utf-8")
    assert "## Typed launch plan" in preview
    assert written["typed_plan"]["content_digest"][:12] in preview


def test_old_request_without_typed_plan_uses_compat_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_dir = tmp_path / "launch"
    launch_cwd = tmp_path / "workspace"
    response_dir.mkdir()
    launch_cwd.mkdir()
    (response_dir / "launch_request.json").write_text(
        json.dumps(
            {
                "request_id": "legacy",
                "dispatch": {"cwd": str(launch_cwd), "prompt": "Do work"},
            }
        ),
        encoding="utf-8",
    )
    seen: dict[str, object] = {}

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        seen["prompt"] = prompt
        seen["cwd"] = Path.cwd()
        return [_agent_result(tmp_path)]

    monkeypatch.setattr("sase.agent.launcher.launch_agents_from_cwd", fake_launch)
    result = dispatch_approved_launch_request(response_dir)
    assert seen["prompt"] == "Do work"
    assert seen["cwd"] == launch_cwd
    assert result.launched_count == 1
    assert result.summary is None


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
    from sase.core.agent_launch_wire import LaunchConditionWire

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
    from sase.core.agent_launch_wire import LaunchConditionWire

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
    from sase.core.agent_launch_wire import LaunchConditionWire

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


def test_proc_unit_dispatches_through_injected_hook(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    plan = _plan(
        LaunchUnitWire(
            logical_id="unit-1",
            source_order=0,
            payload=ProcUnitWire(
                code=_code(),
                workspace=False,
                cwd=str(tmp_path),
            ),
        )
    )
    with patch("sase.procs.store.reserve_proc") as reserve_proc:
        progress, _ = _run_plan(
            tmp_path,
            plan,
            request_id="req-proc",
            proc_dispatcher=lambda unit, fingerprint: (
                True,
                "proc-hook",
                None,
                [],
            ),
        )
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.unit_results[0].outcome == "launched"
    reserve_proc.assert_not_called()


def test_clean_proc_only_admission_does_not_notify(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    plan = _plan(_proc_unit("unit-1", tmp_path))
    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        progress, response_dir = _run_plan(
            tmp_path,
            plan,
            request_id="req-clean-proc",
            proc_dispatcher=lambda unit, fingerprint: (
                True,
                "proc-hook",
                None,
                [],
            ),
        )
    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.unit_results[0].outcome == "launched"
    assert (response_dir / "launch_admission" / "receipt.json").is_file()
    notify.assert_not_called()


def test_agent_only_admission_still_notifies(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        progress, response_dir = _run_plan(
            tmp_path,
            _plan(_agent_unit("unit-1")),
            request_id="req-agent-notify",
            agent_dispatcher=lambda unit, fingerprint: (
                True,
                "reviewer",
                None,
                [_agent_result(tmp_path)],
            ),
        )
    assert progress.admission_complete
    notify.assert_called_once()
    assert notify.call_args.kwargs["success"] is True
    assert notify.call_args.kwargs["extra_files"] == [
        str(response_dir / "launch_admission" / "receipt.json")
    ]


def test_proc_only_launch_error_still_notifies(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        progress, response_dir = _run_plan(
            tmp_path,
            _plan(_proc_unit("unit-1", tmp_path)),
            request_id="req-proc-error",
            proc_dispatcher=lambda unit, fingerprint: (
                False,
                None,
                "spawn failed",
                [],
            ),
        )
    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.launch_errors == 1
    notify.assert_called_once()
    assert notify.call_args.kwargs["success"] is False
    assert notify.call_args.kwargs["extra_files"] == [
        str(response_dir / "launch_admission" / "receipt.json")
    ]


@pytest.mark.parametrize(
    ("verdict", "expected_success"),
    [("skipped", True), ("condition_error", False)],
)
def test_proc_only_condition_terminal_outcomes_still_notify(
    tmp_path: Path,
    verdict: str,
    expected_success: bool,
) -> None:
    pytest.importorskip("sase_core_rs")
    plan = _plan(
        _proc_unit(
            "unit-1",
            tmp_path,
            condition=LaunchConditionWire(code=_code()),
        )
    )
    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        progress, response_dir = _run_plan(
            tmp_path,
            plan,
            request_id=f"req-proc-{verdict}",
            condition_evaluator=lambda unit, waited, context: (verdict, verdict),
            proc_dispatcher=lambda unit, fingerprint: pytest.fail(
                "conditioned proc should not dispatch"
            ),
        )
    assert progress.admission_complete
    assert progress.unit_results[0].outcome == verdict
    notify.assert_called_once()
    assert notify.call_args.kwargs["success"] is expected_success
    assert notify.call_args.kwargs["extra_files"] == [
        str(response_dir / "launch_admission" / "receipt.json")
    ]


def test_typed_dispatch_result_includes_summary(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units("Do work", selected_project="sase")
    response_dir = tmp_path / "bundle"
    response_dir.mkdir()
    data = {
        "request_id": "typed-1",
        "typed_plan": agent_launch_wire_to_json_dict(plan),
        "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
    }
    result = dispatch_typed_launch_request(
        response_dir,
        data,
        spawn_coordinator=False,
        agent_dispatcher=lambda unit, fingerprint: (
            True,
            "reviewer",
            None,
            [_agent_result(tmp_path)],
        ),
    )
    assert result.summary is not None
    assert result.launched_count == 1
    assert result.admission_complete is True
    assert result.summary.launched == 1
    receipt = json.loads(
        (response_dir / "launch_admission" / "receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["plan_digest"] == plan.content_digest


def test_stop_escalates_term_then_exits(tmp_path: Path) -> None:
    import subprocess
    import sys

    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    root = tmp_path / "launch" / "launch_admission"
    root.mkdir(parents=True)
    (root / "sidecar.json").write_text(json.dumps({"pid": child.pid}), encoding="utf-8")
    try:
        stop_launch_admission(tmp_path / "launch")
        child.wait(timeout=8)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
    assert child.returncode is not None


def test_stop_missing_coordinator_is_noop(tmp_path: Path) -> None:
    stop_launch_admission(tmp_path / "missing")


def test_preview_markdown_includes_typed_plan(tmp_path: Path) -> None:
    from sase.agent.launch_executor_types import LaunchExecutionContext
    from sase.core.agent_launch_facade import plan_fake_fanout
    from sase.agent.launch_preview import build_launch_preview_request

    request = build_launch_preview_request(
        plan=plan_fake_fanout("agent", ["Do work"]),
        context=LaunchExecutionContext(
            cl_name="demo",
            project_file=str(tmp_path / "project.sase"),
            project_name="demo",
        ),
        source_surface="cli",
        request_id="preview-typed",
        created_at_unix=1.0,
    )
    request["typed_plan"] = {
        "content_digest": "abc123digest",
        "approval_preview": ["LaunchPlan v1 kind=agent units=1 project=demo"],
    }
    markdown = render_launch_preview_markdown(request)
    assert "## Typed launch plan" in markdown
    assert "digest `abc123digest`" in markdown
    assert "LaunchPlan v1" in markdown


def test_launch_plan_from_dict_round_trips_kind() -> None:
    original = _plan(_agent_unit("unit-1"))
    restored = launch_plan_from_dict(agent_launch_wire_to_json_dict(original))
    assert isinstance(restored.units[0].payload, AgentUnitWire)
    assert restored.units[0].payload.prompt == "Do work"
