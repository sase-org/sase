"""Agent identity and in-memory state helpers for TUI kills."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._dismiss_cleanup import (
    agent_identity_from_wire,
    dismissed_identities_from_plan,
)
from ._clan_cleanup import clan_members_for_container
from ._kill_persistence import AgentIdentity, KillKind

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire


def classify_kill_kind(agent: Agent) -> KillKind | None:
    """Classify the side effects needed to kill an agent.

    UI-free so headless callers (e.g. ``sase plan reject``) classify kills
    the same way the TUI does.
    """
    from ...models.agent import AgentType

    if agent.is_monitor and agent.monitor_state == "running":
        return "monitor"
    workflow = agent.workflow or ""
    if agent.agent_type == AgentType.WORKFLOW:
        return "workflow"
    if workflow.startswith("axe(fix-hook)") or workflow in (
        "fix-hook",
        "summarize-hook",
    ):
        return "hook"
    if workflow.startswith(("axe(mentor)", "mentor(")) or workflow == "mentor":
        return "mentor"
    if workflow.startswith("axe(crs)") or workflow == "crs":
        return "crs"
    if agent.agent_type == AgentType.RUNNING:
        return "running"
    return None


def _immediate_kill_identities(
    agent: Agent, agents_with_children: list[Agent]
) -> set[AgentIdentity]:
    """Return identities hidden immediately after killing an agent."""
    from ...models.agent import AgentType

    identities = {agent.identity}
    identities.update(
        member.identity
        for member in clan_members_for_container(agent, agents_with_children)
    )
    if agent.agent_type == AgentType.WORKFLOW and not agent.is_workflow_child:
        for step in agents_with_children:
            if (
                step.is_workflow_child
                and step.parent_timestamp == agent.raw_suffix
                and step.parent_workflow == agent.workflow
            ):
                identities.add(step.identity)
    return identities


def collect_planned_kill_identities(
    agent: Agent,
    agents_with_children: list[Agent],
    cleanup_plan: AgentCleanupPlanWire | None,
) -> set[AgentIdentity]:
    """Return identities hidden immediately after a planner-backed kill."""
    if cleanup_plan is None:
        return _immediate_kill_identities(agent, agents_with_children)

    identities = dismissed_identities_from_plan(cleanup_plan)
    identities.update(
        agent_identity_from_wire(identity)
        for identity in cleanup_plan.cascaded_workflow_children
    )
    if not identities:
        return _immediate_kill_identities(agent, agents_with_children)
    return identities


def agents_related_to_kill(
    agent: Agent, agents_with_children: list[Agent]
) -> list[Agent]:
    """Return agents whose notifications should be dismissed when killing ``agent``.

    Includes the agent itself, parallel family members, and any workflow-child
    rows when killing a workflow parent (mirroring
    :func:`collect_immediate_kill_identities` but returning Agent objects so
    they can be passed to ``dismiss_notifications_for_agents``).
    """
    from ...models.agent import AgentType

    related: list[Agent] = [
        agent,
        *clan_members_for_container(agent, agents_with_children),
    ]
    if agent.agent_type == AgentType.WORKFLOW and not agent.is_workflow_child:
        for step in agents_with_children:
            if (
                step.is_workflow_child
                and step.parent_timestamp == agent.raw_suffix
                and step.parent_workflow == agent.workflow
            ):
                related.append(step)
    return related


class AgentKillIdentityMixin:
    """Mixin for kill classification, identity collection, and memory updates."""

    _agents: list[Agent]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _agents_with_children: list[Agent]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    current_tab: str

    def _classify_kill_kind(self, agent: Agent) -> KillKind | None:
        """Classify the side effects needed to kill an agent."""
        return classify_kill_kind(agent)

    def _collect_immediate_kill_identities(self, agent: Agent) -> set[AgentIdentity]:
        """Return identities hidden immediately after killing an agent."""
        return _immediate_kill_identities(agent, self._agents_with_children)

    def _collect_planned_kill_identities(
        self, agent: Agent, cleanup_plan: AgentCleanupPlanWire | None
    ) -> set[AgentIdentity]:
        """Return identities hidden immediately after a planner-backed kill."""
        return collect_planned_kill_identities(
            agent, self._agents_with_children, cleanup_plan
        )

    def _plan_focused_agent_cleanup(self, agent: Agent) -> AgentCleanupPlanWire:
        """Plan the focused-row ``x`` cleanup through the Rust-backed facade."""
        from . import _killing as killing_compat

        return killing_compat._plan_single_agent_kill_cleanup(
            agent, list(self._agents_with_children)
        )

    def _agents_related_to_kill(
        self, agent: Agent, agents_with_children_snapshot: list[Agent]
    ) -> list[Agent]:
        """Return agents whose notifications should be dismissed when killing ``agent``.

        Includes the agent itself plus any workflow-child rows when killing a
        workflow parent (mirroring :meth:`_collect_immediate_kill_identities`
        but returning Agent objects so they can be passed to
        ``dismiss_notifications_for_agents``).
        """
        return agents_related_to_kill(agent, agents_with_children_snapshot)

    def _apply_killed_agents_in_memory(
        self, identities: set[AgentIdentity], *, refresh: bool = True
    ) -> None:
        """Remove killed agents from memory and optionally refresh the Agents tab."""
        if not identities:
            return

        # Capture the pre-mutation visible-row anchor so the post-mutation
        # focus lands on the agent visually below the killed one.
        prior_pos = self._capture_focused_visible_pos()  # type: ignore[attr-defined]

        self._dismissed_agents.update(identities)
        for identity in identities:
            self._agent_status_overrides.pop(identity, None)

        # Try the incremental row-removal fast path before mutating
        # ``self._agents`` -- the panel widgets read identities off their
        # cached agent slices, which only match while the app-level list
        # still includes the killed agents.
        fast_path = (
            refresh
            and self.current_tab == "agents"  # type: ignore[attr-defined]
            and hasattr(self, "_try_remove_agent_rows")
            and self._try_remove_agent_rows(identities)  # type: ignore[attr-defined]
        )

        clan_projection_changed = any(
            agent.identity in identities
            and (agent.is_clan_container or agent.tree_parent_key)
            for agent in self._agents_with_children
        )

        self._agents = [a for a in self._agents if a.identity not in identities]  # type: ignore[attr-defined]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in identities
        ]
        if clan_projection_changed:
            from ...models._agent_tree import project_clan_tree

            self._agents_with_children = project_clan_tree(self._agents_with_children)
            self._agents = project_clan_tree(self._agents)
        if hasattr(self, "_invalidate_agent_panel_cache"):
            self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]

        # A visible clan row is derived from the complete cached member set.
        # Re-run the local fold/query pipeline after removing one of those
        # members; projecting the currently-collapsed visible slice alone can
        # otherwise make a non-empty clan disappear until the next disk load.
        if (
            clan_projection_changed and refresh and self.current_tab == "agents"  # type: ignore[attr-defined]
        ):
            self._refilter_agents(prior_pos=prior_pos)  # type: ignore[attr-defined]
            return

        self._restore_focus_after_removal(prior_pos)  # type: ignore[attr-defined]

        if not refresh or self.current_tab != "agents":  # type: ignore[attr-defined]
            return

        if fast_path:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=False, defer_detail=True
            )
        else:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )

    def _clamp_agent_selection(self) -> None:
        """Clamp current_idx after an in-memory agent-list mutation.

        Thin wrapper for callers (revive, hide-toggle) that have no
        pre-mutation visible-row anchor -- delegates to
        :meth:`_restore_focus_after_removal` with ``None`` so the unified
        clamp fallback lives in one place.
        """
        self._restore_focus_after_removal(None)  # type: ignore[attr-defined]
