"""Agent dismissal methods for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures).
from ....changespec import ChangeSpec

from ._dismiss_cleanup import (
    AgentIdentity,
    agent_identity_from_wire,
    agent_wire_identity as _agent_wire_identity,
    apply_dismissal_rename_intents,
    apply_in_memory_reference_rewrites,
    dismissed_identities_from_plan,
    plan_dismissal_side_effects,
    wire_identity_key as _wire_identity_key,
)
from ._dismiss_memory import AgentDismissMemoryMixin
from ._dismiss_persistence import (
    agents_related_to_dismissal,
)
from ._dismiss_persistence import (
    persist_cleanup_side_effect_intents,
    persist_dismiss_side_effects,
)
from ._killing_utils import (
    delete_agent_artifacts,
    dismiss_notifications_for_agents,
    find_workflow_workspace_from_running_field,
)

log = logging.getLogger(__name__)
_agent_identity_from_wire = agent_identity_from_wire
_plan_dismissal_side_effects = plan_dismissal_side_effects
_agents_related_to_dismissal = agents_related_to_dismissal


class AgentDismissingMixin(AgentDismissMemoryMixin):
    """Mixin providing agent dismissal methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    # ChangeSpec state
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: str

    # Agent state
    _agents: list[Agent]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _agents_with_children: list[Agent]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]

    def _dismiss_all_done_agents(self) -> None:
        """Dismiss all done/failed agents after user confirmation."""
        self._dismiss_done_agents_from(
            self._agents_in_focused_panel(),  # type: ignore[attr-defined]
            empty_message="No agents to dismiss",
        )

    def _dismiss_all_done_agents_global(self) -> None:
        """Dismiss all done/failed agents across all loaded panels."""
        self._dismiss_done_agents_from(
            list(self._agents),
            empty_message="No agents to dismiss",
        )

    def _dismiss_done_agents_from(
        self, agents: list[Agent], *, empty_message: str
    ) -> None:
        """Dismiss all done/failed agents from a candidate list."""
        from ._core import DISMISSABLE_STATUSES

        dismissable = [
            a
            for a in agents
            if a.status in DISMISSABLE_STATUSES and a.raw_suffix is not None
        ]

        if not dismissable:
            self.notify(empty_message, severity="warning")  # type: ignore[attr-defined]
            return

        count = len(dismissable)
        s = "s" if count != 1 else ""
        desc_parts = [f"Count: {count} agent{s}"]
        for agent in dismissable:
            name = agent.display_name
            suffix = f" @{agent.agent_name}" if agent.agent_name else ""
            desc_parts.append(f"  {name}{suffix}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmDismissAllModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_dismiss_all(dismissable)

        self.push_screen(ConfirmDismissAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def _do_dismiss_all(self, agents: list[Agent]) -> None:
        """Perform batch dismissal of done/failed agents."""
        if not agents:
            return

        agents_with_children_snapshot = list(self._agents_with_children)

        from sase.agent.names import collect_dismissed_taken_names

        allocated_names: set[str] = collect_dismissed_taken_names()
        cleanup_plan = plan_dismissal_side_effects(
            agents,
            agents_with_children_snapshot,
            taken_dismissed_names=allocated_names,
        )
        name_map = apply_dismissal_rename_intents(
            agents_with_children_snapshot,
            cleanup_plan,
        )
        dismissed_identities = dismissed_identities_from_plan(cleanup_plan)

        for identity in dismissed_identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)
        self._dismissed_agents.update(dismissed_identities)

        count = len(agents)
        s = "s" if count != 1 else ""
        self.notify(f"Dismissed {count} agent{s}")  # type: ignore[attr-defined]
        self._apply_dismissal_in_memory(agents)
        apply_in_memory_reference_rewrites(self._agents_with_children, name_map)
        self._refresh_notification_count()  # type: ignore[attr-defined]

        self.call_later(  # type: ignore[attr-defined]
            self._run_bulk_dismiss_persistence_async,
            list(agents),
            set(self._dismissed_agents),
            agents_with_children_snapshot,
            cleanup_plan,
            name_map,
        )

    async def _run_bulk_dismiss_persistence_async(
        self,
        agents: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        cleanup_plan: object | None = None,
        name_map: dict[str, str] | None = None,
    ) -> None:
        """Persist a batch dismissal's filesystem side effects in a worker."""
        identities = {a.identity for a in agents}
        if identities & self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.update(identities)

        started = time.perf_counter()
        try:
            await asyncio.to_thread(
                persist_bulk_dismiss_transaction,
                agents,
                dismissed_snapshot,
                agents_with_children_snapshot,
                name_map or {},
                cleanup_plan,
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Bulk dismiss cleanup failed: {exc}",
                severity="error",
            )
            self._schedule_agents_async_refresh()  # type: ignore[attr-defined]
        finally:
            self._dismiss_persistence_inflight.difference_update(identities)
            log.debug(
                "bulk agent dismiss persistence: count=%d elapsed=%.3fs",
                len(agents),
                time.perf_counter() - started,
            )

    def _dismiss_done_agent(self, agent: Agent) -> None:
        """Dismiss a DONE or completed workflow agent."""
        if agent.raw_suffix is None:
            self.notify("Cannot dismiss agent: no timestamp", severity="error")  # type: ignore[attr-defined]
            return

        agents_with_children_snapshot = list(self._agents_with_children)
        cleanup_plan = plan_dismissal_side_effects(
            [agent],
            agents_with_children_snapshot,
        )
        self._dismiss_planned_agent(agent, cleanup_plan, agents_with_children_snapshot)

    def _dismiss_planned_agent(
        self,
        agent: Agent,
        cleanup_plan: AgentCleanupPlanWire,
        agents_with_children_snapshot: list[Agent] | None = None,
    ) -> None:
        """Dismiss one agent using an already-computed cleanup plan."""
        from ...models.agent import AgentType

        if agents_with_children_snapshot is None:
            agents_with_children_snapshot = list(self._agents_with_children)
        name_map = apply_dismissal_rename_intents(
            agents_with_children_snapshot,
            cleanup_plan,
        )
        identities = dismissed_identities_from_plan(cleanup_plan)
        if not identities:
            identities = self._collect_dismissal_identities([agent])
        for identity in identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)
        self._dismissed_agents.update(identities)
        self._append_dismissed_agent_objects([agent], identities)

        if agent.agent_type == AgentType.WORKFLOW:
            self.notify(f"Dismissed workflow {agent.workflow}")  # type: ignore[attr-defined]
        else:
            self.notify(f"Dismissed agent for {agent.cl_name}")  # type: ignore[attr-defined]
        self._apply_dismissal_in_memory([agent])
        apply_in_memory_reference_rewrites(self._agents_with_children, name_map)
        self.call_later(  # type: ignore[attr-defined]
            self._run_dismiss_persistence_async,
            agent,
            set(self._dismissed_agents),
            agents_with_children_snapshot,
            cleanup_plan,
            name_map,
        )

    async def _run_dismiss_persistence_async(
        self,
        agent: Agent,
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        cleanup_plan: object | None = None,
        name_map: dict[str, str] | None = None,
    ) -> None:
        """Persist single-agent dismiss side effects in a worker thread."""
        identity = agent.identity
        if identity in self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.add(identity)

        started = time.perf_counter()
        success = True
        try:
            await asyncio.to_thread(
                persist_single_dismiss_transaction,
                agent,
                dismissed_snapshot,
                agents_with_children_snapshot,
                name_map or {},
                cleanup_plan,
            )
        except Exception as exc:
            success = False
            self.notify(  # type: ignore[attr-defined]
                f"Dismiss cleanup failed for {agent.display_name}: {exc}",
                severity="error",
            )
        finally:
            self._dismiss_persistence_inflight.discard(identity)
            log.debug(
                "agent dismiss persistence: identity=%s elapsed=%.3fs",
                identity,
                time.perf_counter() - started,
            )
            if success:
                await self._refresh_notification_count_async()  # type: ignore[attr-defined]
            else:
                self._refresh_notification_count()  # type: ignore[attr-defined]
                self._schedule_agents_async_refresh()  # type: ignore[attr-defined]


def persist_single_dismiss_transaction(
    agent: Agent,
    dismissed_snapshot: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
    name_map: dict[str, str],
    cleanup_plan: object | None = None,
) -> None:
    """Persist all side effects for one optimistic dismiss operation."""
    from ....dismissed_agents import save_dismissed_agents
    from sase.agent.dismissed_name_rewrites import rewrite_dismissed_references

    rewrite_dismissed_references(name_map)
    if not persist_cleanup_side_effect_intents(
        cleanup_plan,
        agents_with_children_snapshot,
    ):
        persist_dismiss_side_effects(agent, agents_with_children_snapshot)
        dismiss_notifications_for_agents(
            agents_related_to_dismissal(agent, agents_with_children_snapshot)
        )
    save_dismissed_agents(dismissed_snapshot)


def persist_bulk_dismiss_transaction(
    agents: list[Agent],
    dismissed_snapshot: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
    name_map: dict[str, str],
    cleanup_plan: object | None = None,
) -> None:
    """Persist all side effects for an optimistic batch dismiss operation."""
    from ....dismissed_agents import save_dismissed_agents
    from sase.agent.dismissed_name_rewrites import rewrite_dismissed_references

    rewrite_dismissed_references(name_map)
    if not persist_cleanup_side_effect_intents(
        cleanup_plan,
        agents_with_children_snapshot,
    ):
        related: list[Agent] = []
        for agent in agents:
            persist_dismiss_side_effects(agent, agents_with_children_snapshot)
            related.extend(
                agents_related_to_dismissal(agent, agents_with_children_snapshot)
            )
        if related:
            dismiss_notifications_for_agents(related)
    save_dismissed_agents(dismissed_snapshot)
