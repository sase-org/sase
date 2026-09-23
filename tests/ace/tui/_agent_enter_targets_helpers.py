"""Shared helpers for Enter-on-agent target tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._agent_enter_action import AgentEnterActionMixin
from sase.ace.tui.actions.agents._agent_enter_targets import (
    AgentEnterResolution,
    PatchSummary,
    build_gate_notification_index,
    resolve_agent_enter_targets,
)
from sase.ace.tui.models.agent import Agent
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
