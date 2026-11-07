"""Durable action submission and roster updates for hijack recovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...models.agent import Agent
from ._hijack_recovery_formatting import int_value


def dismiss_hijacked_agent(app: Any, agent: Agent) -> bool:
    """Dismiss a HIJACKED row through its snapshot-gated durable proc."""
    record = getattr(agent, "hijack_record", None)
    if not isinstance(record, Mapping):
        app.notify(
            "Recovery details are unavailable; refresh the Agents tab",
            severity="warning",
        )
        return False
    return submit_recovery_action(app, agent, dict(record), action="dismiss")


def submit_recovery_action(
    app: Any,
    agent: Agent,
    record: Mapping[str, Any],
    *,
    action: str,
    model: str | None = None,
) -> bool:
    name = str(record.get("agent_name") or agent.agent_name or "")
    hijack_id = str(record.get("hijack_id") or "")
    revision = int_value(record.get("revision"))
    if not name or not hijack_id:
        app.notify("Recovery record is incomplete", severity="error")
        return False
    if getattr(agent, "hijack_overlay", None) == "recovering":
        app.notify("Recovery is already running for this agent", severity="warning")
        return False

    from ..agent_durable import submit_agent_recovery

    agent.hijack_overlay = "recovering"
    _refresh_hijack_row(app, agent)

    def _complete(completion: Any) -> None:
        current = agent_by_identity(app, tuple(agent.identity)) or agent
        current.hijack_overlay = None
        current.hijack_record = None
        _refresh_hijack_row(app, current)
        payload = completion.payload if isinstance(completion.payload, Mapping) else {}
        severity = payload.get("severity")
        if severity not in {"information", "warning", "error"}:
            severity = "information" if completion.success else "error"
        message = completion.message or (
            f"Recovery {action} completed"
            if completion.success
            else f"Recovery {action} failed"
        )
        app.notify(message, severity=severity)
        refresh_source = payload.get("schedule_agents_refresh_source")
        refresh = getattr(app, "_schedule_agents_async_refresh", None)
        if isinstance(refresh_source, str) and callable(refresh):
            refresh(source=refresh_source)

    submitted = submit_agent_recovery(
        app,
        name=name,
        hijack_id=hijack_id,
        expected_revision=revision,
        action=action,
        model=model,
        cl_name=agent.cl_name,
        project_file=agent.project_file,
        display_name=f"Recover {agent.display_name or name}",
        on_complete=_complete,
    )
    if not submitted:
        agent.hijack_overlay = None
        _refresh_hijack_row(app, agent)
        app.notify("Could not queue recovery", severity="error")
    return submitted


def _refresh_hijack_row(app: Any, agent: Agent) -> None:
    from ._roster_generation import notify_roster_status_mutation

    notify_roster_status_mutation(app)
    refresh = getattr(app, "_refresh_agents_display", None)
    if callable(refresh):
        refresh(list_changed=False, defer_detail=True)


def agent_by_identity(app: Any, identity: tuple[object, ...]) -> Agent | None:
    resolver = getattr(app, "_agent_by_identity", None)
    if callable(resolver):
        try:
            found = resolver(identity)
        except Exception:
            found = None
        if isinstance(found, Agent):
            return found
    for row in getattr(app, "_agents_with_children", ()):
        if getattr(row, "identity", None) == identity:
            return row
    return None


__all__ = ["agent_by_identity", "dismiss_hijacked_agent", "submit_recovery_action"]
