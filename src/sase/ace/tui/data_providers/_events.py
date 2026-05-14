"""Daemon delta application for in-memory agent snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..models.agent import Agent
from ._conversion import agent_from_summary, summary_from_delta_fields
from ._handles import daemon_handle_for_agent
from ._normalize import prepare_daemon_agents
from ._types import AgentEventApplyResult


def apply_daemon_agent_events(
    agents: Sequence[Agent],
    event_batch: dict[str, Any],
) -> AgentEventApplyResult:
    """Apply local-daemon agent deltas to a current Agents-tab row snapshot."""

    current = list(agents)
    for event in event_batch.get("events", []):
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict):
            continue
        if "resync_required" in payload:
            reason = payload.get("resync_required")
            if isinstance(reason, dict):
                reason_value = reason.get("reason")
                return AgentEventApplyResult(
                    current,
                    resync_required=True,
                    resync_reason=str(reason_value) if reason_value else None,
                )
            return AgentEventApplyResult(current, resync_required=True)
        delta = payload.get("delta")
        if not isinstance(delta, dict):
            continue
        if str(delta.get("collection", "")).lower() not in {"agents", "artifacts"}:
            continue
        operation = str(delta.get("operation", ""))
        handle = str(delta.get("handle", ""))
        if operation == "invalidate":
            return AgentEventApplyResult(
                current,
                resync_required=True,
                resync_reason=handle or "agent_delta_invalidate",
            )
        if operation == "delete":
            current = [
                agent for agent in current if daemon_handle_for_agent(agent) != handle
            ]
            continue
        if operation in {"insert", "upsert"}:
            fields = delta.get("fields")
            if not isinstance(fields, dict):
                return AgentEventApplyResult(
                    current,
                    resync_required=True,
                    resync_reason="agent_delta_missing_fields",
                )
            incoming = agent_from_summary(summary_from_delta_fields(fields))
            replaced = False
            next_agents: list[Agent] = []
            incoming_handle = daemon_handle_for_agent(incoming)
            for agent in current:
                if daemon_handle_for_agent(agent) == incoming_handle:
                    next_agents.append(incoming)
                    replaced = True
                else:
                    next_agents.append(agent)
            if not replaced:
                next_agents.append(incoming)
            current = prepare_daemon_agents(next_agents)
            continue
        if operation:
            return AgentEventApplyResult(
                current,
                resync_required=True,
                resync_reason=f"unknown_agent_delta_operation:{operation}",
            )
    return AgentEventApplyResult(current)


_apply_daemon_agent_events = apply_daemon_agent_events
