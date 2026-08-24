"""Direct ACE / ``sase run`` typed-admission routing."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launch_admission import (
    dispatch_typed_launch_request,
    run_coordinator_in_bundle,
)
from sase.agent.launch_request_response import read_launch_request
from sase.agent.launch_request_types import (
    DIRECT_TYPED_LAUNCH_KIND,
    ApprovedLaunchDispatchResult,
    TypedAdmissionRequiredError,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchAdmissionSummaryWire,
    LaunchPlanWire,
    LaunchUnitResultWire,
    LaunchUnitWire,
    ProcUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
    launch_plan_from_dict,
)
from sase.feature_flags import override_flags
from sase.notification_gates.paths import REQUEST_FILENAME
from sase.ops.models import DurableOperationRequest
from sase.ops.names import RUN_LAUNCH
from sase.xprompt.code_value import CodeValue


def _agent_result() -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=1234,
        workspace_num=7,
        workspace_dir="/workspace/7",
        output_path="/tmp/out.txt",
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )


def _summary(**overrides: int) -> LaunchAdmissionSummaryWire:
    values = {
        "total": 1,
        "eligible": 1,
        "launched": 1,
        "skipped": 0,
        "condition_errors": 0,
        "launch_errors": 0,
    }
    values.update(overrides)
    return LaunchAdmissionSummaryWire(**values)


def _typed_dispatch_result(data: dict[str, Any]) -> ApprovedLaunchDispatchResult:
    plan = launch_plan_from_dict(dict(data["typed_plan"]))
    launched = sum(
        1 for unit in plan.units if isinstance(unit.payload, ProcUnitWire)
    ) or len(plan.units)
    return ApprovedLaunchDispatchResult(
        request_id=str(data.get("request_id") or "req"),
        results=[],
        summary=_summary(total=len(plan.units), eligible=launched, launched=launched),
        unit_results=tuple(
            LaunchUnitResultWire(logical_id=unit.logical_id, outcome="launched")
            for unit in plan.units
        ),
        plan_digest=str(data.get("plan_digest") or plan.content_digest),
        admission_complete=True,
    )


def _run_launch_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    query: str,
    *,
    payload: dict[str, Any] | None = None,
    typed_launch_units: bool = True,
    capture_typed: bool = True,
    expect_launch_agents: bool = False,
    selected_project: str | None = "sase",
) -> dict[str, Any]:
    from sase.main.query_handler._launch import launch_query

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    captured: dict[str, Any] = {"typed_calls": [], "emit": MagicMock()}
    request_payload = {"prompt": query, **dict(payload or {})}
    request = DurableOperationRequest(operation=RUN_LAUNCH, payload=request_payload)

    def fake_typed_dispatch(
        response_dir: Path, data: Any, **kwargs: Any
    ) -> ApprovedLaunchDispatchResult:
        captured["typed_calls"].append((response_dir, dict(data), kwargs))
        captured["bundle_dir"] = response_dir
        captured["typed_data"] = dict(data)
        return _typed_dispatch_result(dict(data))

    launch_agents = MagicMock(return_value=[_agent_result()])
    with override_flags(typed_launch_units=typed_launch_units), ExitStack() as stack:
        stack.enter_context(patch("sase.ops.cli.load_request", return_value=request))
        stack.enter_context(
            patch(
                "sase.agent.prompt_inputs.missing_required_input_names", return_value=[]
            )
        )
        stack.enter_context(
            patch(
                "sase.xprompt.unresolved.scan_query_for_unresolved_references",
                return_value=[],
            )
        )
        stack.enter_context(
            patch(
                "sase.main.query_handler._launch.launch_agents_from_cwd",
                launch_agents,
            )
        )
        stack.enter_context(
            patch("sase.ops.commands.run.emit_run_launch_result", captured["emit"])
        )
        stack.enter_context(
            patch(
                "sase.notification_gates.service.create_gate",
                side_effect=AssertionError("LaunchApproval must not be created"),
            )
        )
        stack.enter_context(patch("sase.agent.launcher.spawn_agent_subprocess"))
        if selected_project is not None:
            stack.enter_context(
                patch(
                    "sase.agent.direct_typed_launch.resolve_typed_launch_selected_project",
                    lambda prompt: selected_project,
                )
            )
        if capture_typed:
            stack.enter_context(
                patch(
                    "sase.agent.launch_admission.dispatch_typed_launch_request",
                    fake_typed_dispatch,
                )
            )
        with pytest.raises(SystemExit) as exc_info:
            launch_query(query)
    captured["exit"] = exc_info.value
    captured["launch_agents"] = launch_agents
    if expect_launch_agents:
        launch_agents.assert_called()
    else:
        launch_agents.assert_not_called()
    return captured


def test_reported_ace_proc_prompt_uses_typed_admission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    prompt = '#gh:sase %proc("echo hello && sleep 20 && world")'
    captured = _run_launch_query(
        monkeypatch, tmp_path, prompt, payload={"allow_force_reuse": True}
    )
    assert captured["exit"].code == 0
    data = captured["typed_data"]
    plan = launch_plan_from_dict(data["typed_plan"])
    assert len(plan.units) == 1
    assert isinstance(plan.units[0].payload, ProcUnitWire)
    assert "echo hello && sleep 20 && world" in plan.units[0].payload.code.source
    envelope = json.loads(
        (captured["bundle_dir"] / REQUEST_FILENAME).read_text(encoding="utf-8")
    )
    assert envelope["kind"] == DIRECT_TYPED_LAUNCH_KIND
    emit_payload = captured["emit"].call_args.kwargs["payload"]
    assert emit_payload["count"] == 0
    assert emit_payload["results"] == []
    assert emit_payload["request_agents_refresh"] is True
    assert (
        "agent launch produced no results"
        not in captured["emit"].call_args.kwargs["message"]
    )
    assert "launch unit" in captured["emit"].call_args.kwargs["message"]


@pytest.mark.parametrize(
    "prompt",
    [
        '%proc("echo positional")',
        '%proc(python="print(\'ready\')", timeout="20m", label="Preflight")',
        '%proc(timeout="20m", idle_timeout="5m")::\n\n```bash\necho fenced\n```\n',
    ],
)
def test_direct_proc_forms_yield_proc_unit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, prompt: str
) -> None:
    pytest.importorskip("sase_core_rs")
    captured = _run_launch_query(monkeypatch, tmp_path, prompt)
    assert captured["exit"].code == 0
    plan = launch_plan_from_dict(captured["typed_data"]["typed_plan"])
    assert isinstance(plan.units[0].payload, ProcUnitWire)


def test_direct_if_admits_agent_unit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    prompt = "%if::\n\n```bash\ntest -f pyproject.toml\n```\nDo the review"
    captured = _run_launch_query(monkeypatch, tmp_path, prompt)
    assert captured["exit"].code == 0
    plan = launch_plan_from_dict(captured["typed_data"]["typed_plan"])
    assert plan.units[0].condition is not None
    assert isinstance(plan.units[0].payload, AgentUnitWire)


def test_mixed_agent_proc_wait_graph(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    prompt = '%proc("echo first")\n---\n%wait\n%id:reviewer\nReview'
    captured = _run_launch_query(monkeypatch, tmp_path, prompt)
    assert captured["exit"].code == 0
    plan = launch_plan_from_dict(captured["typed_data"]["typed_plan"])
    assert isinstance(plan.units[0].payload, ProcUnitWire)
    assert plan.units[1].waits
    assert plan.units[1].waits[0].kind == "logical"


def test_feature_off_rejects_active_proc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _run_launch_query(
        monkeypatch,
        tmp_path,
        '%proc("echo hello")',
        typed_launch_units=False,
        capture_typed=False,
    )
    assert captured["exit"].code == 1
    captured["launch_agents"].assert_not_called()
    assert captured["emit"].call_args.kwargs["success"] is False
    assert "typed_launch_units" in captured["emit"].call_args.kwargs["message"]


def test_invalid_typed_syntax_fails_before_agent_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    captured = _run_launch_query(
        monkeypatch, tmp_path, "%proc\nDo work", capture_typed=True
    )
    assert captured["exit"].code == 1
    captured["launch_agents"].assert_not_called()
    assert captured["typed_calls"] == []
    assert captured["emit"].call_args.kwargs["success"] is False


def test_literal_and_disabled_proc_keep_legacy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fenced = '```text\n%proc("echo hello")\n```\nDo work'
    captured = _run_launch_query(
        monkeypatch, tmp_path, fenced, expect_launch_agents=True
    )
    assert captured["exit"].code == 0
    assert captured["typed_calls"] == []
    disabled = (
        '%xprompts_enabled:false\n%proc("echo hello")\n%xprompts_enabled:true\nDo work'
    )
    captured = _run_launch_query(
        monkeypatch, tmp_path, disabled, expect_launch_agents=True
    )
    assert captured["exit"].code == 0
    assert captured["typed_calls"] == []
    inline = 'See `%proc("echo hello")` then do work'
    captured = _run_launch_query(
        monkeypatch, tmp_path, inline, expect_launch_agents=True
    )
    assert captured["exit"].code == 0
    assert captured["typed_calls"] == []


def test_feature_on_plain_prompt_keeps_legacy_and_launch_units(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _run_launch_query(
        monkeypatch,
        tmp_path,
        "one\n---\ntwo",
        payload={
            "launch_units": [
                {
                    "prompt": "one",
                    "template_group": "xprompt:team:0",
                    "swarm_xprompts": ["team"],
                }
            ]
        },
        expect_launch_agents=True,
    )
    assert captured["exit"].code == 0
    assert captured["typed_calls"] == []
    _args, kwargs = captured["launch_agents"].call_args
    assert kwargs["launch_units"][0].prompt == "one"


def test_feature_on_force_reuse_without_typed_directive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "sase.agent.force_reuse_launch.plan_force_reuse_launch",
        lambda query: SimpleNamespace(
            rewritten_prompt="%id:foo\nDo work", segment_envs=None
        ),
    )
    monkeypatch.setattr(
        "sase.agent.force_reuse_launch.apply_force_reuse_launch", lambda plan: None
    )
    captured = _run_launch_query(
        monkeypatch,
        tmp_path,
        "%id:!foo\nDo work",
        payload={"allow_force_reuse": True},
        expect_launch_agents=True,
    )
    assert captured["exit"].code == 0
    assert captured["typed_calls"] == []
    assert captured["launch_agents"].call_args.args[0] == "%id:foo\nDo work"


def test_explicit_vcs_target_wins_over_home_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.agent.launch_cwd_common import _KnownProjectVcsLaunchRef

    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda prompt: (
            _KnownProjectVcsLaunchRef(
                "gh", "sase", str(tmp_path), str(tmp_path / "sase.sase")
            )
            if "#gh:sase" in prompt
            else None
        ),
    )
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda create_missing=False: (None, None, None),
    )
    captured = _run_launch_query(
        monkeypatch,
        tmp_path,
        '#gh:sase %proc("echo hello")',
        selected_project=None,
    )
    plan = launch_plan_from_dict(captured["typed_data"]["typed_plan"])
    assert plan.selected_project == "sase"
    assert captured["typed_data"]["selected_project"] == "sase"


def test_direct_bundle_resumes_after_blocked_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.agent.direct_typed_launch import _write_direct_typed_launch_bundle

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    plan = LaunchPlanWire(
        schema_version=1,
        launch_kind="multi_prompt",
        selected_project="sase",
        content_digest="d" * 64,
        units=[
            LaunchUnitWire(
                logical_id="unit-1",
                source_order=0,
                payload=AgentUnitWire(prompt="Review"),
                waits=[WaitTargetWire(kind="agent", name="builder")],
            )
        ],
        approval_preview=["LaunchPlan v1"],
    )
    resolved: list[bool] = [False]

    def wait_resolver(
        _plan: LaunchPlanWire,
        _states: dict[str, dict[str, Any]],
        *,
        now: float,
        waiting_since: Any,
    ) -> list[dict[str, Any]]:
        del now, waiting_since
        return [
            {
                "target": {"kind": "agent", "name": "builder"},
                "resolved": resolved[0],
            }
        ]

    bundle_dir, payload = _write_direct_typed_launch_bundle(
        prompt="%wait(agent=builder)\nReview",
        expanded_prompt="%wait(agent=builder)\nReview",
        typed_plan=agent_launch_wire_to_json_dict(plan),
        source_cwd=str(tmp_path),
        source_surface="cli",
        selected_project="sase",
    )
    first = dispatch_typed_launch_request(
        bundle_dir,
        payload,
        spawn_coordinator=False,
        wait_resolver=wait_resolver,
        agent_dispatcher=lambda unit, fingerprint: (
            True,
            "reviewer",
            None,
            [_agent_result()],
        ),
    )
    assert first.admission_complete is False
    reloaded = read_launch_request(bundle_dir)
    assert reloaded["typed_plan"]["content_digest"] == "d" * 64
    resolved[0] = True
    second = dispatch_typed_launch_request(
        bundle_dir,
        reloaded,
        spawn_coordinator=False,
        wait_resolver=wait_resolver,
        agent_dispatcher=lambda unit, fingerprint: (
            True,
            "reviewer",
            None,
            [_agent_result()],
        ),
    )
    assert second.admission_complete is True
    assert second.summary is not None
    assert second.summary.launched == 1


def test_direct_proc_bundle_coordinator_completion_does_not_notify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.agent.direct_typed_launch import _write_direct_typed_launch_bundle

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    plan = LaunchPlanWire(
        schema_version=1,
        launch_kind="multi_prompt",
        selected_project="sase",
        content_digest="d" * 64,
        units=[
            LaunchUnitWire(
                logical_id="unit-1",
                source_order=0,
                payload=ProcUnitWire(
                    code=CodeValue(
                        source="just check",
                        language="bash",
                        info_string=None,
                        digest="b" * 64,
                        preview="just check",
                    ),
                    workspace=False,
                    cwd=str(tmp_path),
                ),
            )
        ],
        approval_preview=["LaunchPlan v1"],
    )
    bundle_dir, _payload = _write_direct_typed_launch_bundle(
        prompt='%proc("just check")',
        expanded_prompt='%proc("just check")',
        typed_plan=agent_launch_wire_to_json_dict(plan),
        source_cwd=str(tmp_path),
        source_surface="cli",
        selected_project="sase",
    )
    with (
        patch(
            "sase.agent.launch_proc_runtime.dispatch_proc_unit",
            return_value=(True, "proc-hook", None, []),
        ) as dispatch_proc,
        patch("sase.notifications.senders.notify_workflow_complete") as notify,
    ):
        progress = run_coordinator_in_bundle(bundle_dir)

    assert progress.complete
    assert progress.summary.launched == 1
    assert progress.unit_results[0].outcome == "launched"
    dispatch_proc.assert_called_once()
    assert (bundle_dir / "launch_admission" / "receipt.json").is_file()
    notify.assert_not_called()


def test_legacy_agent_path_rejects_enabled_proc_before_llm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda create_missing=False: (None, None, None),
    )
    monkeypatch.setattr(
        "sase.history.prompt.add_or_update_prompt", lambda *a, **k: None
    )
    spawn = MagicMock(side_effect=AssertionError("LLM must not be invoked"))
    monkeypatch.setattr("sase.agent.launcher.spawn_agent_subprocess", spawn)
    from sase.agent.launcher import launch_agents_from_cwd

    with override_flags(typed_launch_units=True):
        with pytest.raises(TypedAdmissionRequiredError, match="typed admission"):
            launch_agents_from_cwd('%proc("echo hello")')
    spawn.assert_not_called()


def test_isolated_direct_bash_proc_settles_without_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.main.query_handler._launch import launch_query
    from sase.procs import wait_for_proc

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    marker = tmp_path / "ran.txt"
    prompt = (
        f'%proc(bash="printf ready > {marker}", workspace="false", cwd="{tmp_path}")'
    )
    emit = MagicMock()
    request = DurableOperationRequest(operation=RUN_LAUNCH, payload={"prompt": prompt})
    with override_flags(typed_launch_units=True):
        with (
            patch("sase.ops.cli.load_request", return_value=request),
            patch(
                "sase.agent.prompt_inputs.missing_required_input_names",
                return_value=[],
            ),
            patch(
                "sase.xprompt.unresolved.scan_query_for_unresolved_references",
                return_value=[],
            ),
            patch("sase.ops.commands.run.emit_run_launch_result", emit),
            patch(
                "sase.notification_gates.service.create_gate",
                side_effect=AssertionError("LaunchApproval must not be created"),
            ),
            patch(
                "sase.agent.launcher.spawn_agent_subprocess",
                side_effect=AssertionError("LLM must not be invoked"),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                launch_query(prompt)
    assert exc_info.value.code == 0
    payload = emit.call_args.kwargs["payload"]
    assert payload["count"] == 0
    assert payload["results"] == []
    identity = payload["unit_results"][0]["identity"]
    finished = wait_for_proc(identity, timeout=10)
    assert finished.status == "success"
    assert finished.origin == "xprompt-proc"
    assert finished.lifecycle == "proc-shell"
    assert marker.read_text(encoding="utf-8") == "ready"
    artifacts = tmp_path / "home" / "projects"
    assert not any(artifacts.rglob("done.json")) if artifacts.exists() else True
