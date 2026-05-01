"""In-memory state updates for agent dismissal."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from ._dismiss_cleanup import AgentIdentity

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


def _is_related_child(agent: Agent, parent: Agent) -> bool:
    """Return True for workflow steps or plan-chain follow-ups of *parent*."""
    return agent.parent_timestamp == parent.raw_suffix and (
        agent.parent_workflow is None or agent.parent_workflow == parent.workflow
    )


class AgentDismissMemoryMixin:
    """Mixin for optimistic in-memory dismissal state changes."""

    _agents: list[Agent]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _agents_with_children: list[Agent]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    current_tab: str

    def _apply_dismissal_in_memory(self, agents: Iterable[Agent]) -> None:
        """Update in-memory agent state after a dismiss without a disk reload.

        Removes the dismissed agents (and workflow-child steps when the
        dismissed agent is a workflow parent) from the cached unfiltered
        agent list, appends them to ``_dismissed_agent_objects`` for
        same-session revive, and re-runs the in-memory filter pipeline.
        """
        from ...models.agent import AgentType

        # Capture the pre-mutation visible-row anchor so focus lands on the
        # agent visually below the dismissed one.
        prior_pos = (
            self._capture_focused_visible_pos()  # type: ignore[attr-defined]
            if hasattr(self, "_capture_focused_visible_pos")
            else None
        )

        agents_list = list(agents)
        if not agents_list:
            self._refilter_agents(prior_pos=prior_pos)  # type: ignore[attr-defined]
            return

        removed: list[Agent] = list(agents_list)
        removed_identities: set[tuple[AgentType, str, str | None]] = {
            a.identity for a in agents_list
        }

        # Include workflow child steps when dismissing a workflow parent.
        for agent in agents_list:
            if (
                agent.agent_type == AgentType.WORKFLOW
                and not agent.is_workflow_child
                and agent.raw_suffix is not None
            ):
                for step in self._agents_with_children:
                    if (
                        (step.is_rendered_workflow_child or step.is_plan_chain_phase)
                        and _is_related_child(step, agent)
                        and step.identity not in removed_identities
                    ):
                        removed.append(step)
                        removed_identities.add(step.identity)

        # Try the incremental row-removal fast path before mutating
        # ``_agents`` / ``_agents_with_children`` so panel widgets can
        # still locate the dismissed identities in their cached slices.
        fast_path = (
            hasattr(self, "_try_remove_agent_rows")
            and self._try_remove_agent_rows(removed_identities)  # type: ignore[attr-defined]
        )

        self._agents_with_children = [
            a
            for a in self._agents_with_children
            if a.identity not in removed_identities
        ]

        # Append to dismissed objects list for same-session revive.
        existing_identities = {a.identity for a in self._dismissed_agent_objects}
        for agent in removed:
            if agent.identity not in existing_identities:
                self._dismissed_agent_objects.append(agent)
                existing_identities.add(agent.identity)

        if fast_path:
            self._apply_dismissal_in_memory_fast_finish(
                removed_identities, prior_pos=prior_pos
            )
            return

        self._refilter_agents(prior_pos=prior_pos)  # type: ignore[attr-defined]

    def _apply_dismissal_in_memory_fast_finish(
        self,
        removed_identities: set[tuple[AgentType, str, str | None]],
        *,
        prior_pos: int | None,
    ) -> None:
        """Finish a fast-path dismissal."""
        self._agents = [a for a in self._agents if a.identity not in removed_identities]
        if hasattr(self, "_invalidate_agent_panel_cache"):
            self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        if hasattr(self, "_restore_focus_after_removal"):
            self._restore_focus_after_removal(prior_pos)  # type: ignore[attr-defined]
        if hasattr(self, "_refresh_tab_bar_agent_counts"):
            self._refresh_tab_bar_agent_counts()  # type: ignore[attr-defined]
        if self.current_tab == "agents":
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=False, defer_detail=True
            )

    def _save_agent_bundle(self, agent: Agent) -> None:
        """Save a serialized bundle of agent data before artifact deletion."""
        from ....dismissed_agents import save_dismissed_bundle

        # Skip ChangeSpec-loaded agents; they persist via .gp file fields.
        if agent._from_changespec:
            return

        save_dismissed_bundle(agent)

        # Also bundle workflow child steps when dismissing a parent.
        if not agent.is_workflow_child and agent.raw_suffix:
            for step in self._agents_with_children:
                if (
                    step.is_rendered_workflow_child or step.is_plan_chain_phase
                ) and _is_related_child(step, agent):
                    save_dismissed_bundle(step)

    def _persist_dismissed_agent(
        self, identity: tuple[AgentType, str, str | None]
    ) -> None:
        """Add an agent identity to the dismissed set and save to disk."""
        from ....dismissed_agents import save_dismissed_agents

        self._dismissed_agents.add(identity)
        save_dismissed_agents(self._dismissed_agents)

    def _collect_dismissal_identities(self, agents: list[Agent]) -> set[AgentIdentity]:
        """Return identities hidden immediately after dismissing agents."""
        from ...models.agent import AgentType

        identities = {a.identity for a in agents}
        for agent in agents:
            if (
                agent.agent_type == AgentType.WORKFLOW
                and not agent.is_workflow_child
                and agent.raw_suffix is not None
            ):
                for step in self._agents_with_children:
                    if (
                        step.is_rendered_workflow_child or step.is_plan_chain_phase
                    ) and _is_related_child(step, agent):
                        identities.add(step.identity)
        return identities

    def _append_dismissed_agent_objects(
        self, agents: list[Agent], identities: set[AgentIdentity]
    ) -> None:
        """Track dismissed objects for same-session revive."""
        if not hasattr(self, "_dismissed_agent_objects"):
            return
        existing = {a.identity for a in self._dismissed_agent_objects}
        for agent in self._agents_with_children:
            if agent.identity in identities and agent.identity not in existing:
                self._dismissed_agent_objects.append(agent)
                existing.add(agent.identity)
        for agent in agents:
            if agent.identity not in existing:
                self._dismissed_agent_objects.append(agent)
                existing.add(agent.identity)
