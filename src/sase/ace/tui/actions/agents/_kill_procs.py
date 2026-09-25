"""Tracked background proc submission for TUI agent kills."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ._kill_persistence import AgentIdentity, BulkKillItem, KillKind
from ._kill_termination import withhold_agent_side_effects
from ._kill_transactions import single_kill_targets

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
        added: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        cleanup_plan: object | None = None,
        recent_group: SavedAgentGroupWire | None = None,
        proc_stops: list[Agent] | None = None,
        gate_cancels: list[Agent] | None = None,
        *,
        on_settled: Callable[[], None] | None = None,
    ) -> None:
        """Submit bulk kill/dismiss persistence as a tracked background proc.

        *on_settled*, when given, is composed with the in-flight-release
        callback below so it always fires exactly once: from the proc's
        settled callback when submission succeeds, or immediately when
        submission is rejected. *proc_stops* and *gate_cancels* ride the
        same durable transaction so member rows stop in one step. *added* is
        the batch's identities, merged into the dismissed index by the proc.
        """
        from . import _killing as killing_compat

        proc_stops = list(proc_stops or ())
        gate_cancels = list(gate_cancels or ())
        member_agents = [*proc_stops, *gate_cancels]

        overlap = {
            item.agent.identity for item in kill_items
        } & self._kill_persistence_inflight
        if overlap:
            # An earlier proc already persists and terminates these rows. Drop
            # only them: the rest of the batch still needs its own proc, and
            # dropping it would leave those processes alive.
            overlapped = [
                item.agent for item in kill_items if item.agent.identity in overlap
            ]
            kill_items = [
                item for item in kill_items if item.agent.identity not in overlap
            ]
            dismissable = [
                agent
                for agent in dismissable
                if agent.identity not in self._kill_persistence_inflight
            ]
            cleanup_plan = withhold_agent_side_effects(
                cleanup_plan, overlapped, agents_with_children_snapshot
            )
            if not kill_items and not dismissable and not member_agents:
                if on_settled is not None:
                    on_settled()
                return
        inflight = {item.agent.identity for item in kill_items} | {
            agent.identity for agent in member_agents
        }
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
            "added_identities": json_identities(added),
            "agents_with_children": serialize_agents(agents_with_children_snapshot),
            "cleanup_plan": (
                agent_cleanup_wire_to_json_dict(cleanup_plan)
                if cleanup_plan is not None
                else None
            ),
            "dismissable": serialize_agents(dismissable),
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
            "proc_stops": serialize_agents(proc_stops),
            "gate_cancels": serialize_agents(gate_cancels),
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
            if on_settled is not None:
                on_settled()

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
            self._escalate_kills_without_cleanup_proc(  # type: ignore[attr-defined]
                item.agent for item in kill_items if item.kind != "monitor"
            )
            resurface = getattr(self, "_resurface_member_rows", None)
            if callable(resurface):
                resurface(member_agents)
            _release()

    def _submit_kill_persistence_proc(
        self,
        agent: Agent,
        kind: KillKind,
        agents_with_children_snapshot: list[Agent] | None = None,
        added: set[AgentIdentity] | None = None,
        cleanup_plan: AgentCleanupPlanWire | None = None,
        *,
        on_settled: Callable[[], None] | None = None,
    ) -> None:
        """Submit single-agent kill persistence as a tracked background proc.

        *on_settled*, when given, is composed with the in-flight-release
        callback below so it always fires exactly once: from the proc's
        settled callback when submission succeeds, or immediately when
        submission is rejected.
        """
        identity = agent.identity
        if identity in self._kill_persistence_inflight:
            if on_settled is not None:
                on_settled()
            return
        self._kill_persistence_inflight.add(identity)

        if agents_with_children_snapshot is None:
            agents_with_children_snapshot = list(self._agents_with_children)
        if added is None:
            added = {agent.identity}
        related_agents = self._agents_related_to_kill(  # type: ignore[attr-defined]
            agent, agents_with_children_snapshot
        )

        from sase.core.agent_cleanup_wire import agent_cleanup_wire_to_json_dict

        from ..cleanup_payload import json_identities, serialize_agent, serialize_agents

        payload = {
            "action": "kill",
            "added_identities": json_identities(added),
            "agent": serialize_agent(agent),
            "agents_with_children": serialize_agents(agents_with_children_snapshot),
            "cleanup_plan": (
                agent_cleanup_wire_to_json_dict(cleanup_plan)
                if cleanup_plan is not None
                else None
            ),
            "identity": str(identity),
            "kind": kind,
            "message": f"Killed {agent.display_name}",
            "refresh_notifications": True,
            "related_agents": serialize_agents(related_agents),
            "transaction": "single_kill",
        }

        def _release() -> None:
            self._kill_persistence_inflight.discard(identity)
            if on_settled is not None:
                on_settled()

        if not self._submit_cleanup_proc(  # type: ignore[attr-defined]
            proc_type="kill",
            display_name=f"kill {agent.display_name}",
            cl_name=agent.cl_name,
            project_file=agent.project_file,
            payload=payload,
            on_settled=_release,
        ):
            self._escalate_kills_without_cleanup_proc(  # type: ignore[attr-defined]
                target
                for target, target_kind in single_kill_targets(
                    agent, kind, cleanup_plan, agents_with_children_snapshot
                )
                if target_kind != "monitor"
            )
            _release()
