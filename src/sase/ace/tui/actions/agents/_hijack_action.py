"""Agents-tab ingress for the durable Agent Hijack stop protocol."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent


def _agent_hijack_enabled() -> bool:
    """Return whether the Agent Hijack beta ingress is enabled."""
    from sase.feature_flags import FeatureFlag, current_flags

    try:
        return bool(current_flags().enabled(FeatureFlag.agent_hijack))
    except Exception:
        return False


def agent_can_offer_hijack(agent: Agent | None) -> bool:
    """Return whether a local live row is a plausible hijack target.

    The stop orchestrator repeats every eligibility check from authoritative
    process, runner metadata, lifecycle, and workspace records. This cheap
    row predicate only decides whether the contextual TUI affordance appears.
    """
    if agent is None or not _agent_hijack_enabled():
        return False
    from ...models.agent import AgentType

    if agent.agent_type is not AgentType.RUNNING:
        return False
    if agent.status not in {"RUNNING", "STARTING", "RETRYING"}:
        return False
    if agent.workspace_num is None or agent.workspace_num <= 0 or agent.pid is None:
        return False
    return not (
        agent.is_monitor
        or agent.is_gate
        or agent.is_named_proc
        or agent.is_clan_container
        or getattr(agent, "fleet_origin_alias", None)
        or getattr(agent, "imported_source_owner", None)
    )


def agent_hijack_ingress_available(agent: Agent | None) -> bool:
    """Return whether leader ingress can act locally or guide a remote user."""
    if agent is None or not _agent_hijack_enabled():
        return False
    from ._remote_lifecycle import is_remote_fleet_agent

    if is_remote_fleet_agent(agent):
        return bool(agent.agent_name)
    return agent_can_offer_hijack(agent)


class AgentHijackActionMixin:
    """Submit eligible hijacks and apply short-lived row presentation."""

    def _start_hijack_agent(self, agent: Agent | None = None) -> bool:
        """Start the durable stop protocol for *agent* or the selected row."""
        if agent is None:
            getter = getattr(self, "_get_selected_agent", None)
            agent = getter() if callable(getter) else None
        if not _agent_hijack_enabled():
            self.notify("Agent hijack is disabled", severity="warning")  # type: ignore[attr-defined]
            return False
        from ._remote_lifecycle import is_remote_fleet_agent

        if agent is not None and is_remote_fleet_agent(agent):
            return self._copy_remote_hijack_command(agent)
        if not agent_can_offer_hijack(agent):
            self.notify(  # type: ignore[attr-defined]
                "Selected agent is not eligible for hijacking",
                severity="warning",
            )
            return False
        assert agent is not None
        name = agent.agent_name
        if not isinstance(name, str) or not name:
            self.notify("Selected row has no local agent name", severity="error")  # type: ignore[attr-defined]
            return False
        if agent.hijack_overlay == "hijacking":
            self.notify("Hijack is already running for this agent")  # type: ignore[attr-defined]
            return False

        from ..agent_durable import submit_agent_hijack

        agent.hijack_overlay = "hijacking"
        self._refresh_hijack_row(agent)  # type: ignore[attr-defined]

        def on_complete(completion: Any) -> None:
            current = next(
                (
                    row
                    for row in getattr(self, "_agents_with_children", ())
                    if row.identity == agent.identity
                ),
                agent,
            )
            current.hijack_overlay = None
            payload = completion.payload
            status = payload.get("status") if isinstance(payload, dict) else None
            current.hijack_stop_failed = status == "stop_failed"
            if status == "held":
                current.hijack_stop_failed = False
            self._refresh_hijack_row(current)  # type: ignore[attr-defined]
            severity = payload.get("severity") if isinstance(payload, dict) else None
            if severity not in {"warning", "error"}:
                severity = "information" if completion.success else "warning"
            if completion.message:
                self.notify(completion.message, severity=severity)  # type: ignore[attr-defined]
            refresh_source = (
                payload.get("schedule_agents_refresh_source")
                if isinstance(payload, dict)
                else None
            )
            if isinstance(refresh_source, str):
                refresh = getattr(self, "_schedule_agents_async_refresh", None)
                if callable(refresh):
                    refresh(source=refresh_source)

        submitted = submit_agent_hijack(
            self,
            name=name,
            identity=str(agent.identity),
            cl_name=agent.cl_name,
            project_file=agent.project_file,
            display_name=f"Hijack {agent.display_name}",
            on_complete=on_complete,
        )
        if not submitted:
            agent.hijack_overlay = None
            self._refresh_hijack_row(agent)  # type: ignore[attr-defined]
            self.notify("Could not queue the hijack operation", severity="error")  # type: ignore[attr-defined]
        return submitted

    def _copy_remote_hijack_command(self, agent: Agent) -> bool:
        """Guide the operator to run the hijack on a remote row's host."""
        alias = str(agent.fleet_origin_alias or "remote")
        name = agent.agent_name
        if not isinstance(name, str) or not name:
            self.notify("Remote row has no agent name", severity="warning")  # type: ignore[attr-defined]
            return False
        command = f"sase agent hijack {shlex.quote(name)}"
        from ..clipboard import schedule_copy_delivery

        schedule_copy_delivery(
            self,
            command,
            copied_label=f"hijack command for {alias}",
            task_name=f"copy-hijack-command-{alias}",
            on_failure="toast",
        )
        self.notify(f"Agent runs on {alias}; copied: {command}")  # type: ignore[attr-defined]
        return True

    def _refresh_hijack_row(self, agent: Agent) -> None:
        """Refresh the row after a transient hijack presentation changes."""
        from ._roster_generation import notify_roster_status_mutation

        notify_roster_status_mutation(self)
        refresh = getattr(self, "_refresh_agents_display", None)
        if callable(refresh):
            refresh(list_changed=False, defer_detail=True)


__all__ = [
    "AgentHijackActionMixin",
    "agent_can_offer_hijack",
    "agent_hijack_ingress_available",
]
