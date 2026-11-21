"""TUI hijack decisions match ``sase agent hijack --explain`` for loader rows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._hijack_decision import compute_hijack_decision
from sase.ace.tui.actions.agents._hijack_roster_snapshot import hijack_row_local_deps
from sase.ace.tui.models.agent import Agent, AgentType
from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack.facts import resolve_and_decide
from sase.agent.names import AgentSession, AgentSessionMember, NamedAgent
from sase.running_field import WorkspaceClaim
from tests._running_field_helpers import create_project_file_with_running


def _tui_agent(
    *,
    name: str,
    status: str = "RUNNING",
    agent_type: AgentType = AgentType.RUNNING,
    artifacts_dir: str | None = None,
    suffix: str | None = None,
    pid: int | None = 421,
    workspace_num: int | None = 4,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name="feature",
        project_file="/tmp/project.sase",
        status=status,
        start_time=datetime(2026, 11, 15, 16, 40, 0),
        workspace_num=workspace_num,
        pid=pid,
        raw_suffix=suffix,
        agent_name=name,
        artifacts_dir=artifacts_dir,
    )


def _decision_key(decision: dict[str, Any], occupant: str | None) -> tuple[Any, ...]:
    return (
        decision.get("mode"),
        decision.get("code"),
        decision.get("redirect_op"),
        occupant,
    )


def _write_member(
    tmp_path: Path,
    *,
    name: str,
    timestamp: str,
    meta: dict[str, Any],
    outcome: str | None = None,
    parent_timestamp: str | None = None,
) -> tuple[AgentSessionMember, Path]:
    artifacts = tmp_path / timestamp
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    member = AgentSessionMember(
        name=name,
        artifacts_dir=artifacts,
        timestamp=timestamp,
        outcome=outcome,
        parent_timestamp=parent_timestamp,
    )
    return member, artifacts


def _install_session_lookups(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session: AgentSession,
    members: tuple[AgentSessionMember, ...],
    project_file: str,
) -> None:
    by_path = {Path(member.artifacts_dir).resolve(): member for member in members}

    def find_session(name: str) -> AgentSession | None:
        if name == session.base_name:
            return session
        if any(member.name == name for member in members):
            return session
        return None

    def find_by_dir(path: str | Path) -> tuple[AgentSession, AgentSessionMember] | None:
        member = by_path.get(Path(path).resolve())
        if member is None:
            return None
        return session, member

    def project_fields(agent: Any) -> tuple[Path, str, str, str, bool]:
        artifacts = Path(agent.artifacts_dir)
        return artifacts, "proj", project_file, artifacts.name, False

    monkeypatch.setattr("sase.agent.names.find_agent_session", find_session)
    monkeypatch.setattr(
        "sase.agent.names.find_agent_session_by_member_artifact_dir",
        find_by_dir,
    )
    monkeypatch.setattr("sase.agent.names.find_agent_clan", lambda _name: None)
    monkeypatch.setattr("sase.agent.running.named_agent_project_fields", project_fields)


_RUNNING_DISPLAY_ALIAS_CASES = (
    ("WORKING TALE", "code"),
    ("WORKING PLAN", "code"),
    ("EPIC APPROVED", "epic"),
    ("PLAN COMMITTED", "commit"),
)


def _named(member: AgentSessionMember, *, done: bool = False) -> NamedAgent:
    return NamedAgent(
        name=member.name,
        artifacts_dir=str(member.artifacts_dir),
        is_done=done,
        outcome=member.outcome,
    )


def test_loader_rows_match_cli_explain_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loader-shaped TUI rows share mode/code/redirect/occupant with CLI explain."""
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                4,
                "ace(run)-20261115_164100",
                "fixture",
                pid=424244,
                artifacts_timestamp="20261115164108",
            ),
            WorkspaceClaim(
                5,
                "ace(run)-20261115_164200",
                "fixture",
                pid=515151,
                artifacts_timestamp="20261115164200",
            ),
            WorkspaceClaim(
                6,
                "ace(run)-20261115_164300",
                "fixture",
                pid=616161,
                artifacts_timestamp="20261115164300",
            ),
        ],
    )
    plan, plan_path = _write_member(
        tmp_path,
        name="tailnet-t.10--plan",
        timestamp="20261115164000",
        meta={"name": "tailnet-t.10--plan", "agent_session_role": "root"},
        outcome="succeeded",
    )
    llm, llm_path = _write_member(
        tmp_path,
        name="tailnet-t.10--5",
        timestamp="20261115164054",
        meta={
            "name": "tailnet-t.10--5",
            "agent_session_role": "agent",
            "lifecycle_phase": "handoff",
            "finalizer_status": {"phase": "executing"},
            "runner_capabilities": ["hijack"],
            "llm_provider": "fakey",
            "model": "fakey-large",
            "pid": 424245,
            "agent_session": "tailnet-t.10",
        },
        parent_timestamp="20261115164000",
    )
    monitor, monitor_path = _write_member(
        tmp_path,
        name="tailnet-t.10--mon-3",
        timestamp="20261115164108",
        meta={
            "name": "tailnet-t.10--mon-3",
            "agent_session": "tailnet-t.10",
            "agent_session_role": "monitor",
            "turn_kind": "monitor",
            "monitor_id": "mon-3",
            "monitor_state": "running",
            "runner_capabilities": ["hijack"],
            "pid": 424243,
        },
        parent_timestamp="20261115164054",
    )
    gate, gate_path = _write_member(
        tmp_path,
        name="tailnet-t.11--gate-1",
        timestamp="20261115164200",
        meta={
            "name": "tailnet-t.11--gate-1",
            "agent_session": "tailnet-t.11",
            "agent_session_role": "gate",
            "turn_kind": "gate",
            "gate_id": "g-1",
            "gate_state": "pending",
            "agent_session_turn": {
                "kind": "gate",
                "id": "g-1",
                "state": "pending",
            },
            "runner_capabilities": ["hijack"],
            "pid": 515151,
        },
    )
    workflow, workflow_path = _write_member(
        tmp_path,
        name="anon-wf.1",
        timestamp="20261115164300",
        meta={
            "name": "anon-wf.1",
            "agent_session": "anon-wf.1",
            "agent_session_role": "agent",
            "runner_capabilities": ["hijack"],
            "llm_provider": "fakey",
            "model": "fakey-large",
            "pid": 616161,
        },
    )
    session_members = (plan, llm, monitor)
    session = AgentSession(
        base_name="tailnet-t.10",
        root=plan,
        members=session_members,
    )
    gate_session = AgentSession(
        base_name="tailnet-t.11",
        root=gate,
        members=(gate,),
    )
    workflow_session = AgentSession(
        base_name="anon-wf.1",
        root=workflow,
        members=(workflow,),
    )
    _install_session_lookups(
        monkeypatch,
        session=session,
        members=session_members,
        project_file=project_file,
    )

    def find_session(name: str) -> AgentSession | None:
        if name in {session.base_name, *(member.name for member in session_members)}:
            return session
        if name in {gate_session.base_name, gate.name}:
            return gate_session
        if name in {workflow_session.base_name, workflow.name}:
            return workflow_session
        return None

    def find_by_dir(path: str | Path) -> tuple[AgentSession, AgentSessionMember] | None:
        wanted = Path(path).resolve()
        for member in (*session_members, gate, workflow):
            if Path(member.artifacts_dir).resolve() == wanted:
                if member in session_members:
                    host = session
                elif member is gate:
                    host = gate_session
                else:
                    host = workflow_session
                return host, member
        return None

    monkeypatch.setattr("sase.agent.names.find_agent_session", find_session)
    monkeypatch.setattr(
        "sase.agent.names.find_agent_session_by_member_artifact_dir",
        find_by_dir,
    )
    monkeypatch.setattr(
        "sase.agent.names.find_agent_clan",
        lambda name: SimpleNamespace(name=name) if name == "wave-1" else None,
    )

    named = {
        plan.name: _named(plan, done=True),
        llm.name: _named(llm),
        monitor.name: _named(monitor),
        gate.name: _named(gate),
        workflow.name: _named(workflow),
        session.base_name: _named(plan, done=True),
    }

    running_rows = [
        SimpleNamespace(
            name=llm.name,
            artifacts_dir=str(llm_path),
            status="RUNNING",
            pid=424245,
            agent_session="tailnet-t.10",
        ),
        SimpleNamespace(
            name=monitor.name,
            artifacts_dir=str(monitor_path),
            status="RUNNING",
            pid=424243,
            agent_session="tailnet-t.10",
            monitor_state="running",
        ),
        SimpleNamespace(
            name=gate.name,
            artifacts_dir=str(gate_path),
            status="RUNNING",
            pid=515151,
            agent_session="tailnet-t.11",
            gate_state="pending",
        ),
        SimpleNamespace(
            name=workflow.name,
            artifacts_dir=str(workflow_path),
            status="RUNNING",
            pid=616161,
        ),
    ]
    deps = StopDeps(
        find_agent=lambda name: named.get(name),
        list_running=lambda: running_rows,
        process_alive=lambda _meta, _path: True,
    )

    container = _tui_agent(
        name=plan.name,
        agent_type=AgentType.WORKFLOW,
        artifacts_dir=str(plan_path),
        suffix=plan.timestamp,
        pid=None,
        status="DONE",
    )
    container.agent_session = session.base_name
    container.agent_session_role = "root"
    container.refresh_raw_presented_agent_name()
    monitor_row = _tui_agent(
        name=monitor.name,
        artifacts_dir=str(monitor_path),
        suffix=monitor.timestamp,
        pid=424243,
    )
    monitor_row.agent_session = session.base_name
    monitor_row.agent_session_role = "monitor"
    container.followup_agents = [monitor_row]
    llm_row = _tui_agent(
        name=llm.name,
        artifacts_dir=str(llm_path),
        suffix=llm.timestamp,
        pid=424245,
    )
    llm_row.agent_session = session.base_name
    gate_row = _tui_agent(
        name=gate.name,
        artifacts_dir=str(gate_path),
        suffix=gate.timestamp,
        pid=515151,
    )
    gate_row.agent_session = gate_session.base_name
    gate_row.agent_session_role = "gate"
    gate_row.gate_id = "g-1"
    workflow_row = _tui_agent(
        name=workflow.name,
        agent_type=AgentType.WORKFLOW,
        artifacts_dir=str(workflow_path),
        suffix=workflow.timestamp,
        pid=616161,
        workspace_num=6,
    )
    clan_row = _tui_agent(name="wave-1", pid=None, workspace_num=None, suffix=None)
    clan_row.is_clan_container = True
    clan_row.agent_clan = "wave-1"
    clan_row.refresh_raw_presented_agent_name()
    remote_row = _tui_agent(name="remote.1")
    remote_row.fleet_origin_alias = "athena"
    done_member, done_path = _write_member(
        tmp_path,
        name="done.1",
        timestamp="20261115163900",
        meta={"name": "done.1", "runner_capabilities": ["hijack"]},
        outcome="succeeded",
    )
    terminal_row = _tui_agent(
        name=done_member.name,
        status="DONE",
        artifacts_dir=str(done_path),
        suffix=done_member.timestamp,
        pid=None,
        workspace_num=None,
    )
    named_row = _tui_agent(name="proc.1", pid=None, workspace_num=None, suffix=None)
    named_row.agent_type = AgentType.NAMED_PROC
    boot, boot_path = _write_member(
        tmp_path,
        name="boot.1",
        timestamp="20261115164400",
        meta={
            "name": "boot.1",
            "lifecycle_phase": "booting",
            "runner_capabilities": ["hijack"],
            "pid": 717171,
        },
    )
    waiting_row = _tui_agent(
        name=boot.name,
        status="WAITING",
        artifacts_dir=str(boot_path),
        suffix=boot.timestamp,
        pid=717171,
        workspace_num=7,
    )

    local_cases = (
        (container, session.base_name),
        (monitor_row, monitor.name),
        (llm_row, llm.name),
        (gate_row, gate.name),
        (workflow_row, workflow.name),
        (clan_row, "wave-1"),
    )
    for row, cli_name in local_cases:
        tui = compute_hijack_decision(row, deps=deps)
        cli_subject, cli_decision = resolve_and_decide(cli_name, deps=deps)
        assert _decision_key(tui.decision, tui.occupant_name) == _decision_key(
            cli_decision, cli_subject.occupant_name
        ), cli_name

    assert container.is_agent_session_container_row
    tui_remote = compute_hijack_decision(remote_row, deps=deps)
    row_subject, row_decision = resolve_and_decide(remote_row, deps=deps)
    assert tui_remote.redirect_op == "copy_remote_command"
    assert _decision_key(
        tui_remote.decision, tui_remote.occupant_name
    ) == _decision_key(row_decision, row_subject.occupant_name)
    tui_clan = compute_hijack_decision(clan_row, deps=deps)
    assert tui_clan.redirect_op == "select_member"
    tui_monitor = compute_hijack_decision(monitor_row, deps=deps)
    assert tui_monitor.mode == "immediate"
    assert tui_monitor.decision["adapter"] == "monitor"
    tui_gate = compute_hijack_decision(gate_row, deps=deps)
    assert tui_gate.redirect_op == "gate_review"
    tui_workflow = compute_hijack_decision(workflow_row, deps=deps)
    assert tui_workflow.mode in {"immediate", "latched"}
    tui_terminal = compute_hijack_decision(terminal_row, deps=deps)
    assert tui_terminal.mode == "refused"
    tui_named = compute_hijack_decision(named_row, deps=deps)
    assert tui_named.mode == "refused"
    waiting_deps = StopDeps(
        find_agent=lambda name: named.get(name),
        list_running=lambda: [
            *running_rows,
            SimpleNamespace(
                name=boot.name,
                artifacts_dir=str(boot_path),
                status="WAITING",
                pid=717171,
            ),
        ],
        process_alive=lambda _meta, _path: True,
    )
    tui_waiting = compute_hijack_decision(waiting_row, deps=waiting_deps)
    assert tui_waiting.mode in {"immediate", "latched", "redirect", "refused"}

    class _Roster:
        _agents_with_children = [
            container,
            monitor_row,
            llm_row,
            gate_row,
            workflow_row,
            clan_row,
            remote_row,
            terminal_row,
            named_row,
            waiting_row,
        ]

    default_keys: dict[str | None, tuple[Any, ...]] = {}
    for row, row_deps in (
        (container, deps),
        (monitor_row, deps),
        (llm_row, deps),
        (gate_row, deps),
        (workflow_row, deps),
        (clan_row, deps),
        (remote_row, deps),
        (terminal_row, deps),
        (named_row, deps),
        (waiting_row, waiting_deps),
    ):
        decided = compute_hijack_decision(row, deps=row_deps)
        default_keys[row.agent_name] = _decision_key(
            decided.decision, decided.occupant_name
        )

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("row-local deps must not scan the archive")

    monkeypatch.setattr("sase.agent.names.find_named_agent", _raise)
    monkeypatch.setattr("sase.agent.names.find_agent_session", _raise)
    monkeypatch.setattr(
        "sase.agent.names.find_agent_session_by_member_artifact_dir",
        _raise,
    )
    monkeypatch.setattr("sase.agent.names.find_agent_clan", _raise)
    monkeypatch.setattr("sase.agent.running_listing.list_running_agents", _raise)

    for row in (
        container,
        monitor_row,
        llm_row,
        gate_row,
        workflow_row,
        clan_row,
        remote_row,
        terminal_row,
        named_row,
        waiting_row,
    ):
        local_deps = hijack_row_local_deps(_Roster(), row)
        local_deps.process_alive = lambda _meta, _path: True
        local = compute_hijack_decision(row, deps=local_deps)
        assert (
            _decision_key(local.decision, local.occupant_name)
            == default_keys[row.agent_name]
        ), row.agent_name


@pytest.mark.parametrize(("row_status", "role"), _RUNNING_DISPLAY_ALIAS_CASES)
def test_working_plan_display_labels_match_cli_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    row_status: str,
    role: str,
) -> None:
    """TUI display aliases on a live coder/epic/commit member hijack as RUNNING."""
    live_timestamp = "20261115164100"
    live_pid = 424244
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                4,
                "ace(run)-20261115_164100",
                "fixture",
                pid=live_pid,
                artifacts_timestamp=live_timestamp,
            )
        ],
    )
    session_name = "bob-cli-o6.4.1.2"
    plan, _plan_path = _write_member(
        tmp_path,
        name=f"{session_name}--plan",
        timestamp="20261115164000",
        meta={
            "name": f"{session_name}--plan",
            "agent_session": session_name,
            "agent_session_role": "root",
        },
        outcome="succeeded",
    )
    live, live_path = _write_member(
        tmp_path,
        name=f"{session_name}--{role}",
        timestamp=live_timestamp,
        meta={
            "name": f"{session_name}--{role}",
            "agent_session": session_name,
            "agent_session_role": role,
            "lifecycle_phase": "provider_running",
            "runner_capabilities": ["hijack"],
            "llm_provider": "fakey",
            "model": "fakey-large",
            "pid": live_pid,
        },
        parent_timestamp=plan.timestamp,
    )
    members = (plan, live)
    session = AgentSession(
        base_name=session_name,
        root=plan,
        members=members,
    )
    _install_session_lookups(
        monkeypatch,
        session=session,
        members=members,
        project_file=project_file,
    )
    named = {
        plan.name: _named(plan, done=True),
        live.name: _named(live),
        session.base_name: _named(plan, done=True),
    }
    tui_row = _tui_agent(
        name=live.name,
        status=row_status,
        artifacts_dir=str(live_path),
        suffix=live.timestamp,
        pid=live_pid,
    )
    tui_row.agent_session = session_name
    tui_row.agent_session_role = role
    cli_running = SimpleNamespace(
        name=live.name,
        artifacts_dir=str(live_path),
        status="RUNNING",
        pid=live_pid,
        agent_session=session_name,
    )
    tui_deps = StopDeps(
        find_agent=lambda name: named.get(name),
        list_running=lambda: [tui_row],
        process_alive=lambda *_: True,
    )
    cli_deps = StopDeps(
        find_agent=lambda name: named.get(name),
        list_running=lambda: [cli_running],
        process_alive=lambda *_: True,
    )

    tui = compute_hijack_decision(tui_row, deps=tui_deps)
    assert tui.mode == "immediate"
    assert tui.code != "ineligible_status"
    assert tui.occupant_name == live.name

    cli_subject, cli_decision = resolve_and_decide(live.name, deps=cli_deps)
    assert _decision_key(tui.decision, tui.occupant_name) == _decision_key(
        cli_decision, cli_subject.occupant_name
    )

    dead_deps = StopDeps(
        find_agent=lambda name: named.get(name),
        list_running=lambda: [tui_row],
        process_alive=lambda *_: False,
    )
    dead = compute_hijack_decision(tui_row, deps=dead_deps)
    assert dead.mode == "refused"
