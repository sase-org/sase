"""Shared setup for the split Agent Hijack action tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._hijack_decision import HijackDecisionView
from sase.ace.tui.models.agent import Agent, AgentType


def make_hijack_agent(*, status: str = "RUNNING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/project.sase",
        status=status,
        start_time=datetime(2026, 11, 3, 10, 0, 0),
        workspace_num=4,
        pid=421,
        raw_suffix="20261103100000",
        agent_name="sase-demo.1",
    )


def make_hijack_view(
    agent: Agent,
    *,
    mode: str,
    code: str | None = None,
    message: str | None = None,
    next_action: str | None = None,
    redirect_op: str | None = None,
    occupant_name: str | None = None,
) -> HijackDecisionView:
    return HijackDecisionView(
        identity=agent.identity,
        roster_generation=0,
        occupant_name=occupant_name or agent.agent_name,
        occupant_reason="test occupant",
        workspace_num=agent.workspace_num,
        decision={
            "mode": mode,
            "code": code,
            "message": message,
            "next_action": next_action,
            "redirect_op": redirect_op,
            "adapter": "llm" if mode == "immediate" else None,
        },
    )


def make_latched_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "hijack_id": "h-latched",
        "agent_name": "sase-demo.1",
        "state": "latched",
        "boundary": "handoff",
        "target_key": "proj:session-1",
        "workspace_num": 4,
        "latched_at": 1_000_000,
    }
    record.update(overrides)
    return record


__all__ = ["make_hijack_agent", "make_hijack_view", "make_latched_record"]
