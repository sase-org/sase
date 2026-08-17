"""Tracked background proc submission for TUI agent kills."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._kill_persistence import AgentIdentity, BulkKillItem, KillKind

if TYPE_CHECKING:
    from ...models import Agent
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire


class AgentKillPersistenceProcMixin:
    """Mixin for submitting kill persistence as tracked cleanup procs."""

    _agents_with_children: list[Agent]
    _dismissed_agents: set[AgentIdentity]
    _kill_persistence_inflight: set[AgentIdentity]

    def _submit_bulk_kill_persistence_proc(
        self,
        kill_items: list[BulkKillItem],
        dismissable: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        cleanup_plan: object | None = None,
        recent_group: SavedAgentGroupWire | None = None,
    ) -> None:
        """Submit bulk kill/dismiss persistence as a tracked background proc."""
        from . import _killing as killing_compat

        inflight = {item.agent.identity for item in kill_items}
        if inflight & self._kill_persistence_inflight:
            return
        self._kill_persistence_inflight.update(inflight)

        killed_count = len(kill_items)
        dismissed_count = len(dismissable)

        from sase.core.agent_cleanup_wire import agent_cleanup_wire_to_json_dict
        from sase.core.agent_group_archive_wire import (
            saved_agent_group_wire_to_json_dict,
        )

        from ..cleanup_payload import json_identities, serialize_agents

        payload = {
            "action": "kill",
            "agents_with_children": serialize_agents(agents_with_children_snapshot),
            "cleanup_plan": (
                agent_cleanup_wire_to_json_dict(cleanup_plan)
                if cleanup_plan is not None
                else None
            ),
            "dismissable": serialize_agents(dismissable),
            "dismissed_identities": json_identities(dismissed_snapshot),
            "identity": ",".join(sorted(str(item) for item in inflight)),
            "kill_items": [
                {
                    "agent": serialize_agents([item.agent])[0],
                    "identities": json_identities(item.identities),
                    "kind": item.kind,
                }
                for item in kill_items
            ],
            "message": killing_compat._bulk_kill_summary(killed_count, dismissed_count),
            "recent_group": (
                saved_agent_group_wire_to_json_dict(recent_group)
                if recent_group is not None
                else None
            ),
            "refresh_notifications": True,
            "transaction": "bulk_kill",
        }

        def _release() -> None:
            self._kill_persistence_inflight.difference_update(inflight)

        if not self._submit_cleanup_proc(  # type: ignore[attr-defined]
            proc_type="kill",
            display_name=killing_compat._bulk_kill_task_display_name(
                killed_count, dismissed_count
            ),
            cl_name="",
            project_file="",
            payload=payload,
            on_settled=_release,
        ):
            _release()

    def _submit_kill_persistence_proc(
        self,
        agent: Agent,
        kind: KillKind,
        agents_with_children_snapshot: list[Agent] | None = None,
        dismissed_snapshot: set[AgentIdentity] | None = None,
        cleanup_plan: AgentCleanupPlanWire | None = None,
    ) -> None:
        """Submit single-agent kill persistence as a tracked background proc."""
        identity = agent.identity
        if identity in self._kill_persistence_inflight:
            return
        self._kill_persistence_inflight.add(identity)

        if agents_with_children_snapshot is None:
            agents_with_children_snapshot = list(self._agents_with_children)
        if dismissed_snapshot is None:
            from ....dismissed_agents import snapshot_dismissed_agents

            dismissed_snapshot = snapshot_dismissed_agents(self._dismissed_agents)
        related_agents = self._agents_related_to_kill(  # type: ignore[attr-defined]
            agent, agents_with_children_snapshot
        )

        from sase.core.agent_cleanup_wire import agent_cleanup_wire_to_json_dict

        from ..cleanup_payload import json_identities, serialize_agent, serialize_agents

        payload = {
            "action": "kill",
            "agent": serialize_agent(agent),
            "agents_with_children": serialize_agents(agents_with_children_snapshot),
            "cleanup_plan": (
                agent_cleanup_wire_to_json_dict(cleanup_plan)
                if cleanup_plan is not None
                else None
            ),
            "dismissed_identities": json_identities(dismissed_snapshot),
            "identity": str(identity),
            "kind": kind,
            "message": f"Killed {agent.display_name}",
            "refresh_notifications": True,
            "related_agents": serialize_agents(related_agents),
            "transaction": "single_kill",
        }

        def _release() -> None:
            self._kill_persistence_inflight.discard(identity)

        if not self._submit_cleanup_proc(  # type: ignore[attr-defined]
            proc_type="kill",
            display_name=f"kill {agent.display_name}",
            cl_name=agent.cl_name,
            project_file=agent.project_file,
            payload=payload,
            on_settled=_release,
        ):
            _release()
