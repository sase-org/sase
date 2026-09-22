"""Resolver, label, index, and executor coverage for Enter-on-agent."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._agent_enter_action import AgentEnterActionMixin
from sase.ace.tui.actions.agents._agent_enter_targets import (
    AgentEnterResolution,
    PatchSummary,
    _gate_target_label,
    build_gate_notification_index,
    resolve_agent_enter_targets,
)
from sase.ace.tui.actions.agents._patch_navigation import (
    AgentPatchNavigationMixin,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import Notification

from ._agent_unread_helpers import make_agent


def _notification(
    notification_id: str,
    action: str | None,
    *,
    timestamp: str = "2026-09-18T12:00:00+00:00",
    action_data: dict[str, str] | None = None,
    files: list[str] | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=timestamp,
        sender="test",
        action=action,
        action_data=dict(action_data or {}),
        files=list(files or []),
    )


def _matching_action_data(agent: Agent) -> dict[str, str]:
    assert agent.raw_suffix is not None
    data: dict[str, str] = {
        "agent_cl_name": agent.cl_name,
        "agent_timestamp": agent.raw_suffix,
    }
    if agent.agent_name:
        data["agent_name"] = agent.agent_name
    return data


def _gate_row(
    suffix: str,
    *,
    gate_id: str = "gate-abc123",
    kind: str = "sudo",
    state: str = "pending",
    start_status: str = "SUDO",
    stop_status: str | None = None,
    stop_time: datetime | None = None,
    notification_id: str | None = None,
    bundle_path: str | None = None,
    label: str | None = None,
    start_time: datetime | None = None,
) -> Agent:
    return replace(
        make_agent(
            name=f"gate-{suffix}",
            status="GATE",
            raw_suffix=f"20260918{suffix}",
            start_time=start_time,
        ),
        agent_family_role="gate",
        gate_id=gate_id,
        gate_kind=kind,
        gate_state=state,
        gate_start_status=start_status,
        gate_stop_status=stop_status,
        stop_time=stop_time,
        gate_notification_id=notification_id,
        gate_bundle_path=bundle_path,
        gate_label=label,
    )


def _patch_name_for(agent: Agent) -> str | None:
    name = agent.cl_name
    if not name or name in {"unknown", "~"}:
        return None
    return name


def _summary_lookup(name: str) -> PatchSummary | None:
    return PatchSummary(status="Mailed", pr_label="PR #7")


def _resolve(
    agent: Agent,
    notifications: list[Notification] | None = None,
    *,
    patch_lookup: Any = _summary_lookup,
) -> AgentEnterResolution:
    index = build_gate_notification_index(list(notifications or []))
    return resolve_agent_enter_targets(
        agent,
        gate_notifications=index,
        patch_name_for=_patch_name_for,
        patch_lookup=patch_lookup,
    )


def _sources(resolution: AgentEnterResolution) -> list[str]:
    return [target.source for target in resolution.targets]


# ---------------------------------------------------------------------------
# Scope basics
# ---------------------------------------------------------------------------


def test_standalone_patch_only_row() -> None:
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    resolution = _resolve(agent)
    assert len(resolution.targets) == 1
    [target] = resolution.targets
    assert target.kind == "patch"
    assert target.source == "patch"
    assert target.key == "patch:demo"
    assert target.label == "Go to Patch"
    assert target.patch_name == "demo"
    assert resolution.primary == target
    assert resolution.empty_message is None


def test_patch_sentinels_have_no_patch_target() -> None:
    for name in ("~", "unknown"):
        agent = make_agent(name=name, raw_suffix="20260918010102")
        resolution = _resolve(agent)
        assert resolution.targets == ()


def test_patch_mixin_rejects_running_marker() -> None:
    class _PatchApp(AgentPatchNavigationMixin):
        _agents_with_children: list[Agent] = []

    app = _PatchApp()
    assert (
        app._resolve_agent_cl_name(make_agent(name="~", raw_suffix="20260918010103"))
        is None
    )
    assert (
        app._resolve_agent_cl_name(
            make_agent(name="unknown", raw_suffix="20260918010104")
        )
        is None
    )
    assert (
        app._resolve_agent_cl_name(make_agent(name="real", raw_suffix="20260918010105"))
        == "real"
    )


def test_pending_sudo_gate_row() -> None:
    agent = _gate_row("010101", notification_id="n-sudo")
    resolution = _resolve(agent)
    assert len(resolution.targets) == 1
    [target] = resolution.targets
    assert target.kind == "gate"
    assert target.source == "gate_row"
    assert target.key == "gate:gate-abc123"
    assert target.label == "Review sudo request"
    assert target.badge is not None and target.badge.startswith("SUDO")
    assert target.notification_id == "n-sudo"
    assert target.gate_id == "gate-abc123"


@pytest.mark.parametrize(
    ("kind", "start_status", "label", "expected"),
    [
        ("launch", "LAUNCH", None, "Approve agent launch"),
        ("hitl", "HITL", None, "Respond to checkpoint"),
        ("plan", "TALE", None, "Review tale plan"),
        ("plan", "PLAN", None, "Review plan"),
        ("epic_plan", "EPIC", None, "Review epic plan"),
        ("task_triage", "GATE", None, "Triage task"),
        ("custom", "GATE", "Do the thing", "Do the thing"),
        ("custom", "GATE", None, "Open gate"),
        ("mystery", "GATE", None, "Open gate"),
    ],
)
def test_gate_row_labels(
    kind: str, start_status: str, label: str | None, expected: str
) -> None:
    agent = _gate_row(
        "020202",
        gate_id=f"gate-{kind}",
        kind=kind,
        start_status=start_status,
        label=label,
    )
    [target] = _resolve(agent).targets
    assert target.label == expected


def test_settled_gate_row_reports_settled_message() -> None:
    agent = _gate_row(
        "030303",
        state="answered",
        stop_time=datetime(2026, 9, 18, 13, 0, 0),
        stop_status="APPROVED",
    )
    resolution = _resolve(agent)
    assert resolution.targets == ()
    assert resolution.empty_message == "This gate already settled (APPROVED)"


def test_settling_gate_row_is_not_a_target() -> None:
    agent = _gate_row("040404", state="settling")
    resolution = _resolve(agent)
    assert resolution.targets == ()
    assert resolution.empty_message == "This gate already settled (settling)"


def test_container_mirroring_gate_state_has_no_phantom_gate() -> None:
    container = replace(
        make_agent(name="fam-root", raw_suffix="20260918010101"),
        agent_family_role="root",
        agent_family="fam",
        agent_name="starter",
        gate_state="pending",
        gate_start_status="SUDO",
        followup_agents=[],
    )
    assert container.is_gate is False
    resolution = _resolve(container)
    assert "gate_row" not in _sources(resolution)


def test_clan_container_points_inside() -> None:
    agent = replace(
        make_agent(name="clan-row", raw_suffix="20260918010101"),
        is_clan_container=True,
        agent_clan="testclan",
    )
    resolution = _resolve(agent)
    assert resolution.targets == ()
    assert resolution.empty_message == "Select an agent inside this clan"


def test_monitor_and_proc_rows_are_silent() -> None:
    monitor = replace(
        make_agent(name="mon", raw_suffix="20260918010101"),
        agent_family_role="monitor",
    )
    assert monitor.is_monitor is True
    assert _resolve(monitor).targets == ()

    proc = replace(
        make_agent(name="proc", raw_suffix="20260918010102"),
        agent_type=AgentType.PROC_SHELL,
    )
    assert proc.is_proc_shell is True
    assert _resolve(proc).targets == ()


# ---------------------------------------------------------------------------
# Family scopes
# ---------------------------------------------------------------------------


def _family(
    *,
    members: list[Agent],
    root_name: str = "fam-root",
    root_suffix: str = "20260918010101",
    root_cl: str = "fam-root",
) -> Agent:
    root = replace(
        make_agent(name=root_cl, raw_suffix=root_suffix),
        agent_family_role="root",
        agent_family="fam",
        agent_name="starter",
        followup_agents=list(members),
    )
    for member in members:
        member.family_container = root
    return root


def test_container_collects_member_gate_rows() -> None:
    gate = _gate_row("010101", notification_id="n-gate")
    member = make_agent(name="worker", raw_suffix="20260918010202")
    root = _family(members=[member, gate])
    resolution = _resolve(root)
    kinds = _sources(resolution)
    assert "gate_row" in kinds
    assert resolution.targets[0].source == "gate_row"
    assert resolution.targets[-1].source == "patch"


def test_container_matches_member_identity_notifications() -> None:
    member = make_agent(name="worker", raw_suffix="20260918010202")
    root = _family(members=[member])
    notification = _notification(
        "n-plan",
        "PlanApproval",
        action_data=_matching_action_data(member),
        files=["/tmp/plans/review_plan_enter_keymap.md"],
    )
    resolution = _resolve(root, [notification])
    assert [t.key for t in resolution.targets] == ["gate:n-plan", "patch:fam-root"]
    [gate_target, _] = resolution.targets
    assert gate_target.label == "Review plan"
    assert gate_target.detail == "review_plan_enter_keymap.md"


def test_member_creator_back_reference_matches() -> None:
    member = replace(
        make_agent(name="worker", raw_suffix="20260918010202"),
        gate_id="gate-creator-1",
    )
    assert member.is_gate is False
    gate = _gate_row("010101", gate_id="gate-creator-1")
    member = replace(member, followup_agents=[gate])
    root = _family(members=[member])
    gate.family_container = root
    resolution = _resolve(member)
    assert [t.key for t in resolution.targets] == [
        "gate:gate-creator-1",
        "patch:worker",
    ]


def test_member_gate_creator_agent_matches() -> None:
    member = replace(
        make_agent(name="worker", raw_suffix="20260918010202"),
        agent_name="creator-agent",
    )
    gate = replace(
        _gate_row("010101", gate_id="gate-other-1"),
        gate_creator_agent="creator-agent",
    )
    member = replace(member, followup_agents=[gate])
    root = _family(members=[member])
    gate.family_container = root
    resolution = _resolve(member)
    assert resolution.targets[0].key == "gate:gate-other-1"


def test_row_backed_target_wins_over_notification_duplicate() -> None:
    agent = _gate_row(
        "010101",
        notification_id="n-dup",
        bundle_path="/tmp/bundles/gate-abc123",
    )
    notification = _notification(
        "n-dup",
        "SudoRequest",
        action_data={
            **_matching_action_data(agent),
            "bundle_path": "/tmp/bundles/gate-abc123",
        },
    )
    resolution = _resolve(agent, [notification])
    assert len(resolution.targets) == 1
    assert resolution.targets[0].source == "gate_row"


def test_settled_bundle_drops_notification_only_target() -> None:
    # A notification-only target whose bundle belongs to a settled gate row
    # in the roster is dropped.
    member = make_agent(name="worker", raw_suffix="20260918010303")
    settled_gate = _gate_row(
        "040404",
        gate_id="gate-settled",
        state="answered",
        stop_time=datetime(2026, 9, 18, 13, 0, 0),
        bundle_path="/tmp/bundles/gate-settled",
    )
    root = _family(members=[member, settled_gate], root_cl="~")
    stale = _notification(
        "n-stale",
        "CustomGate",
        action_data={
            **_matching_action_data(member),
            "bundle_path": "/tmp/bundles/gate-settled",
        },
    )
    resolution = _resolve(root, [stale])
    assert "notification" not in _sources(resolution)


def test_old_plan_approval_found_behind_newer_notifications() -> None:
    agent = replace(
        make_agent(name="target", status="PLAN", raw_suffix="20260918010101"),
        agent_name="target-agent",
    )
    newer = [
        _notification(
            f"newer-{index}", "JumpToPatch", timestamp="2026-09-19T12:00:00+00:00"
        )
        for index in range(120)
    ]
    old = _notification(
        "old-match",
        "PlanApproval",
        timestamp="2026-09-18T12:00:00+00:00",
        action_data=_matching_action_data(agent),
    )
    resolution = _resolve(agent, [*newer, old])
    assert "gate:old-match" in [t.key for t in resolution.targets]


def test_container_falls_back_to_newest_member_patch() -> None:
    member = make_agent(name="member-patch", raw_suffix="20260918010202")
    gate = _gate_row("010101")
    root = _family(members=[member, gate], root_cl="~")
    resolution = _resolve(root)
    assert resolution.targets[-1].key == "patch:member-patch"
    assert resolution.targets[-1].project_file == member.project_file


def test_ordering_gates_newest_first_patch_last() -> None:
    old_gate = _gate_row(
        "010101",
        gate_id="gate-old",
        start_time=datetime(2026, 9, 18, 10, 0, 0),
    )
    new_gate = _gate_row(
        "020202",
        gate_id="gate-new",
        kind="launch",
        start_status="LAUNCH",
        start_time=datetime(2026, 9, 18, 12, 0, 0),
    )
    root = _family(members=[old_gate, new_gate])
    resolution = _resolve(root)
    assert [t.key for t in resolution.targets] == [
        "gate:gate-new",
        "gate:gate-old",
        "patch:fam-root",
    ]
    assert resolution.primary is not None
    assert resolution.primary.key == "gate:gate-new"
    assert resolution.primary.label == "Approve agent launch"


# ---------------------------------------------------------------------------
# Legacy and remote scopes
# ---------------------------------------------------------------------------


def test_standalone_waiting_input_gets_hitl_target() -> None:
    agent = make_agent(name="wf", status="WAITING INPUT", raw_suffix="20260918010101")
    resolution = _resolve(agent)
    assert _sources(resolution) == ["workflow_hitl", "patch"]
    [hitl, _] = resolution.targets
    assert hitl.label == "Respond to checkpoint"
    assert hitl.key.startswith("hitl:workflow:")


def test_standalone_question_gets_marker_target() -> None:
    agent = make_agent(name="q", status="QUESTION", raw_suffix="20260918010101")
    resolution = _resolve(agent)
    assert _sources(resolution) == ["question_marker", "patch"]
    [marker, _] = resolution.targets
    assert marker.label == "Answer question"


def test_gate_target_suppresses_question_marker() -> None:
    agent = make_agent(name="q", status="QUESTION", raw_suffix="20260918010101")
    notification = _notification(
        "n-q",
        "UserQuestion",
        action_data=_matching_action_data(agent),
    )
    resolution = _resolve(agent, [notification])
    assert _sources(resolution) == ["notification", "patch"]


def test_workflow_step_hitl_scope() -> None:
    agent = replace(
        make_agent(name="step", status="WAITING INPUT", raw_suffix="20260918010101"),
        parent_workflow="wf-name",
    )
    resolution = _resolve(agent)
    assert _sources(resolution) == ["workflow_hitl", "patch"]


def _remote_agent(*, pending: bool) -> Agent:
    attention: dict[str, Any] | None = (
        {"state": "pending", "kind": "question", "title": "Help?"}
        if pending
        else {"state": "answered", "kind": "question"}
    )
    return replace(
        make_agent(name="remote-row", raw_suffix="20260918010101"),
        fleet_origin_alias="farhost",
        fleet_attention=attention,
        fleet_capabilities={"resource": ["attention.answer_question"]},
    )


def test_remote_attention_scope() -> None:
    resolution = _resolve(_remote_agent(pending=True))
    assert len(resolution.targets) == 1
    [target] = resolution.targets
    assert target.source == "remote_attention"
    assert target.label == "Answer remote request"
    assert target.detail == "Help?"


def test_remote_without_attention_has_no_targets() -> None:
    assert _resolve(_remote_agent(pending=False)).targets == ()


# ---------------------------------------------------------------------------
# Labels and index
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "pending_status", "fallback", "expected"),
    [
        ("plan", "TALE", None, "Review tale plan"),
        ("plan", "tale", None, "Review tale plan"),
        ("plan", "PLAN", None, "Review plan"),
        ("epic_plan", "EPIC", None, "Review epic plan"),
        ("question", None, None, "Answer question"),
        ("sudo", "SUDO", None, "Review sudo request"),
        ("launch", None, None, "Approve agent launch"),
        ("hitl", None, None, "Respond to checkpoint"),
        ("task_triage", None, None, "Triage task"),
        ("bead_snooze", None, None, "Review snoozed bead"),
        ("flag_triage", None, None, "Triage flag"),
        ("bead_stale_cleanup", None, None, "Clean up stale beads"),
        ("plugins_required", None, None, "Install required plugins"),
        ("custom", None, "Do the thing", "Do the thing"),
        ("custom", None, None, "Open gate"),
        (None, None, None, "Open gate"),
        ("mystery", None, None, "Open gate"),
    ],
)
def test_gate_target_label_table(
    kind: str | None, pending_status: str | None, fallback: str | None, expected: str
) -> None:
    assert (
        _gate_target_label(
            kind=kind, pending_status=pending_status, fallback_label=fallback
        )
        == expected
    )


def test_gate_notification_index_prefilters_and_caches() -> None:
    gate = _notification(
        "n-gate",
        "SudoRequest",
        action_data={"bundle_path": "/tmp/b/1", "raw_suffix": "20260918010101"},
    )
    plain = _notification("n-plain", "JumpToPatch")
    snapshot = [gate, plain]
    first = build_gate_notification_index(snapshot)
    assert build_gate_notification_index(snapshot) is first
    assert first.by_id["n-gate"] is gate
    assert first.by_bundle_path["/tmp/b/1"] is gate
    assert first.by_raw_suffix["20260918010101"] == [gate]
    assert [n.id for n in first.gate_notifications] == ["n-gate"]
    second = build_gate_notification_index([gate])
    assert second is not first


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class _EnterApp(AgentEnterActionMixin):
    def __init__(
        self,
        *,
        notifications: list[Notification] | None = None,
        agents: list[Agent] | None = None,
    ) -> None:
        self._notification_snapshot_cache: Any = SimpleNamespace(
            notifications=list(notifications or [])
        )
        self.patches: list[Any] = []
        self._agents = list(agents or [])
        self.notifies: list[tuple[str, Any]] = []
        self.refreshes = 0
        self.pending_reads = 0
        self.marker_result = True
        self.marker_calls: list[Agent] = []
        self.hitls: list[Agent] = []
        self.remotes: list[Any] = []
        self.stored_snapshots: list[Any] = []

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifies.append((message, severity))

    def _resolve_agent_cl_name(self, agent: Agent) -> str | None:
        return _patch_name_for(agent)

    def _agent_by_identity(self, identity: tuple[object, ...]) -> Agent | None:
        for agent in self._agents:
            if agent.identity == identity:
                return agent
        return None

    def _open_question_modal_from_marker(self, agent: Agent) -> bool:
        self.marker_calls.append(agent)
        return self.marker_result

    def _answer_workflow_hitl(self, agent: Agent) -> None:
        self.hitls.append(agent)

    def _answer_remote_attention_for(self, agent: Any) -> None:
        self.remotes.append(agent)

    def _schedule_notification_snapshot_refresh(self) -> None:
        self.refreshes += 1

    def _read_notification_pending_actions_from_provider(self) -> object:
        self.pending_reads += 1
        return object()

    def _set_notification_snapshot_cache(self, snapshot: Any) -> None:
        self.stored_snapshots.append(snapshot)
        self._notification_snapshot_cache = snapshot

    def call_from_thread(self, callback: Any, *args: Any) -> None:
        callback(*args)


def test_executor_runs_patch_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    app = _EnterApp(agents=[agent])
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_navigation.navigate_to_patch_tab",
        lambda app_arg, patch_name, project_file: (
            calls.append((patch_name, project_file)) or True
        ),
    )
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None and resolution.primary.kind == "patch"
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    assert calls == [("demo", agent.project_file)]


def test_executor_dispatches_snapshot_hit_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _gate_row("010101", notification_id="n-sudo")
    notification = _notification(
        "n-sudo", "SudoRequest", action_data=_matching_action_data(agent)
    )
    app = _EnterApp(notifications=[notification], agents=[agent])
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_dispatch.open_notification_action",
        lambda app_arg, note: dispatched.append(note.id) or True,
    )
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    assert dispatched == ["n-sudo"]
    assert app.refreshes == 1


def test_executor_miss_without_notification_id_toasts() -> None:
    agent = _gate_row("010101", gate_id="abcdef123456")
    app = _EnterApp(agents=[agent])
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    assert app.notifies == [("Gate abcdef is no longer pending", "warning")]


def test_executor_question_marker_paths() -> None:
    agent = make_agent(name="q", status="QUESTION", raw_suffix="20260918010101")
    app = _EnterApp(agents=[agent])
    resolution = app._agent_enter_resolution(agent)
    marker = next(t for t in resolution.targets if t.source == "question_marker")
    app._run_agent_enter_target(marker, agent_identity=agent.identity)
    assert app.marker_calls == [agent]
    assert app.notifies == []

    app.marker_result = False
    app._run_agent_enter_target(marker, agent_identity=agent.identity)
    assert app.notifies == [("No pending question found for this agent", "warning")]


def test_executor_hitl_and_remote_branches() -> None:
    hitl_agent = make_agent(
        name="wf", status="WAITING INPUT", raw_suffix="20260918010101"
    )
    remote_agent = _remote_agent(pending=True)
    app = _EnterApp(agents=[hitl_agent, remote_agent])

    hitl_resolution = app._agent_enter_resolution(hitl_agent)
    hitl = next(t for t in hitl_resolution.targets if t.source == "workflow_hitl")
    app._run_agent_enter_target(hitl, agent_identity=hitl_agent.identity)
    assert app.hitls == [hitl_agent]

    remote_resolution = app._agent_enter_resolution(remote_agent)
    [remote_target] = remote_resolution.targets
    app._run_agent_enter_target(remote_target, agent_identity=remote_agent.identity)
    assert app.remotes == [remote_agent]


def test_executor_gone_agent_toasts() -> None:
    agent = make_agent(name="q", status="QUESTION", raw_suffix="20260918010101")
    app = _EnterApp(agents=[])
    resolution = app._agent_enter_resolution(agent)
    marker = next(t for t in resolution.targets if t.source == "question_marker")
    app._run_agent_enter_target(marker, agent_identity=agent.identity)
    assert app.notifies == [("Agent is no longer visible", "warning")]


async def test_executor_off_thread_detail_fallback_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _gate_row("010101", notification_id="n-missing")
    app = _EnterApp(agents=[agent])
    loaded = _notification("n-missing", "SudoRequest")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_provider.read_notification_detail_for_tui",
        lambda notification_id: SimpleNamespace(
            value=SimpleNamespace(notification=loaded)
        ),
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_dispatch.open_notification_action",
        lambda app_arg, note: dispatched.append(note.id) or True,
    )
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    [task] = list(app._agent_enter_async_tasks)
    await task
    await asyncio.sleep(0)
    assert dispatched == ["n-missing"]
    assert app.refreshes == 1


async def test_executor_revalidation_toast_when_target_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _gate_row("010101", notification_id="n-missing")
    app = _EnterApp(agents=[agent])
    loaded = _notification("n-missing", "SudoRequest")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_provider.read_notification_detail_for_tui",
        lambda notification_id: SimpleNamespace(
            value=SimpleNamespace(notification=loaded)
        ),
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_dispatch.open_notification_action",
        lambda app_arg, note: dispatched.append(note.id) or True,
    )
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    # The gate settles while the detail read is in flight.
    agent.gate_state = "answered"
    agent.stop_time = datetime(2026, 9, 18, 13, 0, 0)
    [task] = list(app._agent_enter_async_tasks)
    await task
    await asyncio.sleep(0)
    assert dispatched == []
    assert ("Gate gate-a is no longer pending", "warning") in app.notifies


async def test_executor_load_failure_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _gate_row("010101", gate_id="abcdef123456", notification_id="n-missing")
    app = _EnterApp(agents=[agent])

    def _fail(notification_id: str) -> Any:
        raise FileNotFoundError("gone")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_provider.read_notification_detail_for_tui",
        _fail,
    )
    resolution = app._agent_enter_resolution(agent)
    assert resolution.primary is not None
    app._run_agent_enter_target(resolution.primary, agent_identity=agent.identity)
    [task] = list(app._agent_enter_async_tasks)
    await task
    await asyncio.sleep(0)
    assert app.notifies == [
        ("Couldn't load gate abcdef; try: sase gate show abcdef", "warning")
    ]


def test_ensure_snapshot_short_circuits_when_cached() -> None:
    app = _EnterApp()
    calls: list[str] = []
    app._ensure_agent_enter_snapshot(lambda: calls.append("then"))
    assert calls == ["then"]
    assert app.stored_snapshots == []


async def test_ensure_snapshot_reads_off_pump_once() -> None:
    app = _EnterApp()
    app._notification_snapshot_cache = None
    snapshot = SimpleNamespace(notifications=[])
    app._read_notification_snapshot_from_provider = lambda **kwargs: snapshot  # type: ignore[method-assign]
    calls: list[str] = []
    app._ensure_agent_enter_snapshot(lambda: calls.append("then"))
    [task] = list(app._agent_enter_async_tasks)
    await task
    await asyncio.sleep(0)
    assert calls == ["then"]
    assert app.stored_snapshots == [snapshot]
