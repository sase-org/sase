"""Fakey ``%auto:tale`` lifecycle e2e (``%auto`` E1 ``cli`` phase).

Scenario: a ``%auto:tale`` planner, its auto-approved tale plan, the
coder (inherits ``tale``), a monitor started by the coder, the monitor
follow-up (inherits ``tale``), a gate created by the follow-up, and the
gate follow-up (inherits ``tale``). The epic plan proposed in the gate
follow-up parks. In a second scenario, ``A`` off mid-chain makes the next
follow-up park.

This is function-driven, not provider-driven: it drives the real
successor helper (``create_followup_artifacts``, which the inherit phase
wired for in-process coders, question successors, pipe, gate-turn
members, and monitor members) and the real gate creation (execution
side effects stubbed, as in the contract harness). No provider is
invoked and nothing on the decision path is mocked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.autonomy.record import read_record

from tests.autonomy_contract import harness
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def _gate_policies(
    artifacts_dir: Path,
    tale_plan: Path,
    epic_plan: Path,
    monkeypatch: Any,
    tag: str,
) -> dict[str, dict[str, Any]]:
    """Create real tale and epic gates from live meta; return policies."""
    from sase.plan_gate import build_plan_approval_gate_spec

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
    )

    policies: dict[str, dict[str, Any]] = {}
    for kind, plan_file in (("plan", tale_plan), ("epic_plan", epic_plan)):
        auto_action = get_auto_plan_approval_action()
        auto_argument = get_auto_plan_approval_argument()
        if auto_argument is None and auto_action in {"tale", "epic"}:
            auto_argument = auto_action
        spec = build_plan_approval_gate_spec(
            str(plan_file),
            f"{kind}-{tag}",
            auto_enabled=auto_action is not None,
            auto_argument=auto_argument,
        )
        gate = harness.create_plan_gate_isolated(spec, artifacts_dir, f"{kind}-{tag}")
        resolved = gate.to_dict().get("auto_resolution") or {}
        policies[kind] = dict(resolved.get("policy") or {})
        policies[f"{kind}_state"] = {"state": resolved.get("state")}
    return policies


def _artifact_timestamp(artifacts_dir: Path) -> str:
    """Return the real timestamp used by the artifacts directory."""
    timestamp = artifacts_dir.name
    assert len(timestamp) == 14 and timestamp.isdigit()
    return timestamp


def _prepare_real_coder_successor(
    planner_meta: dict[str, Any], planner_dir: Path, workdir: Path
) -> tuple[dict[str, Any], Path]:
    """Create a real coder member through the in-process successor entrypoint."""
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState
    from sase.axe.run_agent_successor import SuccessorRequest, continue_as_successor
    from sase.plan_chain import set_agent_session_fields

    set_agent_session_fields(planner_meta, session="contract-agent", role="root")
    planner_meta["role_suffix"] = "--0"
    harness.write_meta(planner_dir, planner_meta)
    context = AgentExecContext(
        cl_name="contract-agent",
        project_file=str(workdir / "project.sase"),
        workspace_dir=str(workdir),
        output_path=str(workdir / "output.txt"),
        workspace_num=0,
        timestamp="261010_120000",
        update_target="",
        project_name="contract-proj",
        is_home_mode=True,
        artifacts_dir=str(planner_dir),
        artifacts_timestamp="20261010120000",
        vcs_tag=None,
        agent_name="contract-agent",
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta=planner_meta,
        local_macros={},
    )
    state = LoopState(
        current_prompt="Plan the work.",
        current_role_suffix="--0",
        current_artifacts_dir=str(planner_dir),
        loop_outcome="",
        sdd_spec_path=None,
        original_prompt="%auto:tale\nPlan the work.",
    )
    continue_as_successor(
        context,
        state,
        SuccessorRequest(
            base_meta=planner_meta,
            prompt="Implement the approved tale plan.",
            suffix="--code",
            agent_session_role="coder",
        ),
        # Session promotion and prompt archival are surrounding workflow
        # effects; the successor creation/inheritance path stays real here.
        promote=lambda *_args, **_kwargs: None,
        store_prompt=lambda *_args, **_kwargs: None,
    )
    coder_dir = Path(state.current_artifacts_dir)
    return harness.read_meta(coder_dir), coder_dir


def _attach_plan(parent_dir: Path, project_name: str, suffix: str):
    """Build the resolver output consumed by the real detached-child path."""
    from sase.agent._agent_session_attach_types import AgentSessionAttachLaunchPlan
    from sase.plan_chain import agent_session_value

    parent_meta = harness.read_meta(parent_dir)
    parent_name = str(parent_meta.get("name") or "contract-agent")
    parent_base = str(agent_session_value(parent_meta) or "contract-agent")
    child_number = len(list(parent_dir.parent.glob("*/agent_meta.json"))) + 1
    child_name = f"{parent_base}--followup-{child_number}"
    return AgentSessionAttachLaunchPlan(
        parent_arg=parent_base,
        suffix_arg=suffix,
        parent_name=parent_name,
        parent_base=parent_base,
        parent_timestamp=_artifact_timestamp(parent_dir),
        parent_artifacts_dir=str(parent_dir),
        role_suffix=f"--followup-{child_number}",
        agent_name=child_name,
        agent_session_role="coder",
        parent_agent_session_member_name=parent_name,
        parent_agent_session_role_suffix=str(parent_meta.get("role_suffix") or "--0"),
        parent_needs_rename=False,
        parent_project_name=project_name,
        parent_workspace_dir=str(parent_meta.get("workspace_dir") or ""),
        parent_workspace_num=int(parent_meta.get("workspace_num") or 0),
        host_composed=False,
    )


def _install_followup_spawn(
    monkeypatch: Any,
    tmp_path: Path,
    followup_module: Any,
    parent_dir: Path,
) -> list[tuple[dict[str, Any], Path, str]]:
    """Stub workspace allocation and provider spawn while keeping attach/inherit real."""
    from sase.agent import _agent_session_attach_resolution as resolution
    from sase.agent._agent_session_attach_launch import (
        load_agent_session_attach_plan_from_env,
    )
    from sase.agent.launch_types import AgentLaunchResult
    from sase.turns.followup import FollowupLaunchResult

    children: list[tuple[dict[str, Any], Path, str]] = []

    def resolve(_directive, *, project_name: str, **_kwargs):
        return _attach_plan(parent_dir, project_name, "@")

    def fake_provider_spawn(**kwargs: Any) -> AgentLaunchResult:
        env = dict(kwargs.get("extra_env") or {})
        attach_plan = load_agent_session_attach_plan_from_env(env)
        assert attach_plan is not None
        assert attach_plan.host_composed is True
        child_name = attach_plan.agent_name
        prompt = str(kwargs["prompt"])
        child_meta = harness.build_meta_for_prompt(
            prompt,
            tmp_path,
            agent_name=child_name,
            attach_plan=attach_plan,
        )
        child_timestamp = f"202610101200{len(children) + 1:02d}"
        child_dir = tmp_path / "launched" / child_timestamp
        child_dir.mkdir(parents=True, exist_ok=True)
        harness.write_meta(child_dir, child_meta)
        (child_dir / "raw_prompt.md").write_text(prompt, encoding="utf-8")
        children.append((child_meta, child_dir, prompt))
        return AgentLaunchResult(
            pid=400000 + len(children),
            workspace_num=int(kwargs.get("workspace_num") or 0),
            workspace_dir=str(kwargs.get("workspace_dir") or tmp_path),
            output_path=str(child_dir / "output.txt"),
            project_name=str(kwargs.get("project_name") or "contract-proj"),
            agent_name=child_name,
            artifacts_dir=str(child_dir),
        )

    def allocate_and_launch(**kwargs: Any) -> FollowupLaunchResult:
        prompt = kwargs["compose_prompt"](None)
        result = kwargs["spawn"](
            prompt,
            str(kwargs["meta_workspace_dir"]),
            int(kwargs["meta_workspace_num"] or 0),
            kwargs["transfer_from_pid"],
            kwargs.get("recorded_vcs_ref"),
        )
        return kwargs["record_launched"](
            result.agent_name,
            artifacts_dir=result.artifacts_dir or None,
            pid=result.pid,
        )

    monkeypatch.setattr(followup_module, "launch_turn_followup", allocate_and_launch)
    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_provider_spawn)
    # The monitor module binds the initial resolver at import time. Gate turns
    # use detached_child's module reference; both resolve against this live
    # member's metadata for host-side attach composition.
    if hasattr(followup_module, "resolve_agent_session_attach_plan"):
        monkeypatch.setattr(
            followup_module, "resolve_agent_session_attach_plan", resolve
        )
    monkeypatch.setattr(resolution, "resolve_agent_session_attach_plan", resolve)
    return children


def _create_monitor_member(parent_meta: dict[str, Any], parent_dir: Path) -> Path:
    from sase.monitor.member import create_monitor_member
    from sase.plan_chain import agent_session_value

    artifacts = Path(
        create_monitor_member(
            "contract-proj",
            parent_meta,
            lane=str(agent_session_value(parent_meta) or "contract-agent"),
            suffix="--monitor",
            prev_artifacts_timestamp=_artifact_timestamp(parent_dir),
            workspace_num=0,
            monitor_id=f"monitor-{parent_dir.name}",
            command="true",
            cwd=str(parent_meta.get("workspace_dir") or "."),
            label="Lifecycle monitor",
            reason="exercise the monitor successor path",
            next_action="Summarize the completed monitor run.",
            start_status="MONITORING",
            stop_status="MONITORED",
            timeout_seconds=5.0,
            tail_lines=20,
            next_output="none",
            request_fingerprint=f"lifecycle-{parent_dir.name}",
        )
    )
    return artifacts


def _create_gate_member(parent_meta: dict[str, Any], parent_dir: Path) -> Path:
    from sase.gate_turn.member import create_gate_turn_member
    from sase.notification_gates.model_turn import GateTurnSpec
    from sase.plan_chain import agent_session_value

    shell = {
        "pending_status": "REVIEW",
        "settled_status": "REVIEWED",
        "workspace": "inherit",
        "next": {
            "prompt": "Continue with the approved follow-up.",
            "output": ["results"],
            "fork": "turn",
            "raw_prompt": True,
        },
    }
    turn = GateTurnSpec.from_mapping(shell, branches=(("approve",),))
    return Path(
        create_gate_turn_member(
            "contract-proj",
            parent_meta,
            lane=str(agent_session_value(parent_meta) or "contract-agent"),
            suffix="--gate",
            prev_artifacts_timestamp=_artifact_timestamp(parent_dir),
            workspace_num=0,
            gate_id=f"gate-{parent_dir.name}",
            gate_kind="custom",
            label="Lifecycle gate",
            reason="exercise the gate successor path",
            creator_agent=str(parent_meta.get("name") or "contract-agent"),
            timeout_seconds=60.0,
            request_fingerprint=f"gate-lifecycle-{parent_dir.name}",
            turn=turn,
        )
    )


def _launch_gate_followup(
    monkeypatch: Any,
    tmp_path: Path,
    gate_dir: Path,
) -> tuple[dict[str, Any], Path, str]:
    import sase.gate_turn.followup as followup_module
    from sase.gate_turn.followup import launch_gate_followup_agent
    from sase.gate_turn.followup_policy import resolve_gate_followup

    meta = harness.read_meta(gate_dir)
    shell = {
        "pending_status": "REVIEW",
        "settled_status": "REVIEWED",
        "workspace": "inherit",
        "next": {
            "prompt": "Continue with the approved follow-up.",
            "output": ["results"],
            "fork": "turn",
            "raw_prompt": True,
        },
    }
    envelope = {
        "kind": "custom",
        "request_id": str(meta["gate_id"]),
        "presentation": {"title": "Lifecycle gate"},
        "options": [],
        "branches": [["approve"]],
        "shell": shell,
    }
    response = {"selected_option_ids": []}
    policy = resolve_gate_followup(
        envelope,
        gate_state="answered",
        response=response,
    )
    assert policy is not None
    children = _install_followup_spawn(monkeypatch, tmp_path, followup_module, gate_dir)
    result = launch_gate_followup_agent(
        str(gate_dir),
        meta,
        project_name="contract-proj",
        gate_state="answered",
        policy=policy,
        envelope=envelope,
        response=response,
        settle_timeout_seconds=0.0,
    )
    assert result.launched is True
    assert len(children) == 1
    return children[0]


def _create_plans(workdir: Path, tmp_path: Path, monkeypatch: Any):
    home = tmp_path / ".sase"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    workdir.mkdir()
    tale_plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    epic_plan = harness.write_plan_file(workdir, "epic.md", VALID_EPIC_PLAN)
    _, planner_meta, planner_dir = harness.launch_meta(
        "%auto:tale\nDo the work", workdir
    )
    return tale_plan, epic_plan, planner_meta, planner_dir


def _launch_monitor_followup(
    tmp_path: Path, monkeypatch: Any, monitor_dir: Path
) -> tuple[dict[str, Any], Path, str]:
    import sase.monitor.followup as followup_module
    from sase.monitor.output import OutputCapture

    meta = harness.read_meta(monitor_dir)
    children = _install_followup_spawn(
        monkeypatch, tmp_path, followup_module, monitor_dir
    )
    capture = OutputCapture()
    capture.append_bytes(b"monitor completed\n")
    result = followup_module.launch_followup_agent(
        str(monitor_dir),
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=0.1,
        capture=capture,
        project_name="contract-proj",
        settle_timeout_seconds=0.0,
    )
    assert result.launched is True
    assert len(children) == 1
    return children[0]


def test_tale_lifecycle_inherits_to_gate_followup(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A ``%auto:tale`` chain inherits to the gate follow-up; epics park."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    tale_plan, epic_plan, planner_meta, planner_dir = _create_plans(
        workdir, tmp_path, monkeypatch
    )
    assert read_record(planner_meta)["profile"] == "tale"

    # Its tale plan auto-approves with policy `auto`.
    policies = _gate_policies(planner_dir, tale_plan, epic_plan, monkeypatch, "planner")
    assert policies["plan"]["outcome"] == "auto"
    assert policies["plan"]["value"] == "approve_archive"

    # The coder inherits `tale` through the real in-process successor helper.
    coder_meta, coder_dir = _prepare_real_coder_successor(
        planner_meta, planner_dir, workdir
    )
    coder_record = read_record(coder_meta)
    assert coder_record is not None
    assert coder_record["profile"] == "tale"
    assert coder_record["source"] == "inherited"

    # Create a real monitor member and run its production follow-up path.
    monitor_dir = _create_monitor_member(coder_meta, coder_dir)
    monitor_meta = harness.read_meta(monitor_dir)
    assert read_record(monitor_meta)["profile"] == "tale"
    followup_meta, followup_dir, _ = _launch_monitor_followup(
        tmp_path, monkeypatch, monitor_dir
    )
    assert read_record(followup_meta)["profile"] == "tale"

    # A gate created by the follow-up auto-resolves its tale plan ...
    followup_policies = _gate_policies(
        followup_dir, tale_plan, epic_plan, monkeypatch, "followup"
    )
    assert followup_policies["plan"]["outcome"] == "auto"

    # ... and a real gate member plus its follow-up inherit `tale` ...
    gate_dir = _create_gate_member(followup_meta, followup_dir)
    gate_meta = harness.read_meta(gate_dir)
    assert read_record(gate_meta)["profile"] == "tale"
    gate_followup_meta, gate_followup_dir, _ = _launch_gate_followup(
        monkeypatch, tmp_path, gate_dir
    )
    assert read_record(gate_followup_meta)["profile"] == "tale"

    # ... so the epic plan proposed there parks for a human.
    gate_followup_policies = _gate_policies(
        gate_followup_dir, tale_plan, epic_plan, monkeypatch, "gate-followup"
    )
    assert gate_followup_policies["epic_plan"]["outcome"] == "ask"
    assert gate_followup_policies["epic_plan_state"]["state"] == "disabled"


def test_a_off_mid_chain_parks_next_followup(tmp_path: Path, monkeypatch: Any) -> None:
    """``A`` off mid-chain means the next follow-up parks everything."""
    from sase.ace.tui.actions.agents._directive_persistence import (
        persist_autonomy_toggle,
    )

    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    tale_plan, epic_plan, planner_meta, planner_dir = _create_plans(
        workdir, tmp_path, monkeypatch
    )
    coder_meta, coder_dir = _prepare_real_coder_successor(
        planner_meta, planner_dir, workdir
    )
    monitor_dir = _create_monitor_member(coder_meta, coder_dir)
    followup_meta, followup_dir, _ = _launch_monitor_followup(
        tmp_path, monkeypatch, monitor_dir
    )
    assert read_record(followup_meta)["profile"] == "tale"

    # `A` off on the live follow-up through the real toggle mutation.
    (followup_dir / "raw_prompt.md").write_text(
        "%auto:tale\nDo the work", encoding="utf-8"
    )
    persist_autonomy_toggle(followup_dir, "manual", surface="tui")
    toggled = harness.read_meta(followup_dir)
    assert read_record(toggled)["profile"] == "manual"

    # Create and settle a real gate turn after A-off; its follow-up stays manual.
    gate_dir = _create_gate_member(toggled, followup_dir)
    gate_meta = harness.read_meta(gate_dir)
    assert read_record(gate_meta)["profile"] == "manual"
    next_meta, next_dir, _ = _launch_gate_followup(monkeypatch, tmp_path, gate_dir)
    assert read_record(next_meta)["profile"] == "manual"
    policies = _gate_policies(next_dir, tale_plan, epic_plan, monkeypatch, "after")
    assert policies["plan"]["outcome"] == "ask"
    assert policies["epic_plan"]["outcome"] == "ask"
