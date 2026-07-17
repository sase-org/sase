"""In-memory state updates for agent dismissal."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ._dismiss_cleanup import AgentIdentity
from ._clan_cleanup import clan_members_for_container
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


# Hard cap on the live ``_dismissed_agent_objects`` list. The on-disk
# dismissed-id registry remains the source of truth for cross-session
# state; this cap keeps the in-memory revive/refresh hot-path bounded so
# `O(N)` scans don't blow up over long sessions.
DISMISSED_AGENT_OBJECTS_MAX = 500


def trim_dismissed_agent_objects(agents: list[Agent]) -> list[Agent]:
    """Return *agents* trimmed to the most-recent ``DISMISSED_AGENT_OBJECTS_MAX``."""
    if len(agents) <= DISMISSED_AGENT_OBJECTS_MAX:
        return agents
    return agents[-DISMISSED_AGENT_OBJECTS_MAX:]


class AgentDismissMemoryMixin:
    """Mixin for optimistic in-memory dismissal state changes."""

    _agents: list[Agent]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _revived_agent_raw_suffixes: set[str]
    _agents_with_children: list[Agent]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _agent_neighbor_index_cache: tuple[Any, ...] | None
    _dismiss_revive_epoch: int
    current_tab: str

    def _bump_dismiss_revive_epoch(self) -> None:
        """Invalidate neighbor relationships that depend on dismissed objects."""
        self._dismiss_revive_epoch = getattr(self, "_dismiss_revive_epoch", 0) + 1
        if hasattr(self, "_agent_neighbor_index_cache"):
            self._agent_neighbor_index_cache = None

    def _clear_revived_agent_suffixes(self, agents: Iterable[Agent]) -> None:
        """Stop preserving revived rows once they are dismissed again."""
        revived_suffixes = getattr(self, "_revived_agent_raw_suffixes", None)
        if not revived_suffixes:
            return
        dismissed_suffixes = {
            agent.raw_suffix for agent in agents if agent.raw_suffix is not None
        }
        revived_suffixes.difference_update(dismissed_suffixes)

    def _apply_dismissal_in_memory(self, agents: Iterable[Agent]) -> None:
        """Update in-memory agent state after a dismiss without a disk reload.

        Removes the dismissed agents (plus parallel family members and
        workflow-child steps that cascade from a dismissed root) from the
        cached unfiltered agent list, appends them to
        ``_dismissed_agent_objects`` for same-session revive, and re-runs the
        in-memory filter pipeline.
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
        self._bump_dismiss_revive_epoch()

        removed: list[Agent] = list(agents_list)
        removed_identities: set[tuple[AgentType, str, str | None]] = {
            a.identity for a in agents_list
        }

        # Include parallel members and workflow steps when dismissing a root.
        for agent in agents_list:
            for member in clan_members_for_container(
                agent,
                self._agents_with_children,
            ):
                if member.identity not in removed_identities:
                    removed.append(member)
                    removed_identities.add(member.identity)
            if (
                agent.agent_type == AgentType.WORKFLOW
                and not agent.is_workflow_child
                and agent.raw_suffix is not None
            ):
                for step in self._agents_with_children:
                    if (
                        step.is_workflow_child
                        and step.parent_timestamp == agent.raw_suffix
                        and step.parent_workflow == agent.workflow
                        and step.identity not in removed_identities
                    ):
                        removed.append(step)
                        removed_identities.add(step.identity)

        self._clear_revived_agent_suffixes(removed)

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
        if any(agent.is_clan_container or agent.tree_parent_key for agent in removed):
            from ...models._agent_tree import project_clan_tree

            self._agents_with_children = project_clan_tree(self._agents_with_children)

        # Append to dismissed objects list for same-session revive.
        existing_identities = {a.identity for a in self._dismissed_agent_objects}
        for agent in removed:
            if agent.identity not in existing_identities:
                self._dismissed_agent_objects.append(agent)
                existing_identities.add(agent.identity)
        self._dismissed_agent_objects = trim_dismissed_agent_objects(
            self._dismissed_agent_objects
        )

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
        if self.current_tab == "agents":
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=False, defer_detail=True
            )

    def _save_agent_bundle(self, agent: Agent) -> None:
        """Save a serialized bundle of agent data before artifact deletion."""
        from ....dismissed_agents import save_dismissed_bundle

        # Skip ChangeSpec-loaded agents; they persist via project spec file fields.
        if agent._from_changespec:
            return

        save_dismissed_bundle(agent)

        # Also bundle workflow child steps when dismissing a parent.
        if not agent.is_workflow_child and agent.raw_suffix:
            for step in self._agents_with_children:
                if (
                    step.is_workflow_child
                    and step.parent_timestamp == agent.raw_suffix
                    and step.parent_workflow == agent.workflow
                ):
                    save_dismissed_bundle(step)

    def _persist_dismissed_agent(
        self, identity: tuple[AgentType, str, str | None]
    ) -> None:
        """Add an agent identity to the dismissed set and save to disk."""
        from ....dismissed_agents import save_dismissed_agents

        self._dismissed_agents.add(identity)
        self._bump_dismiss_revive_epoch()
        revived_suffixes = getattr(self, "_revived_agent_raw_suffixes", None)
        if revived_suffixes and identity[2] is not None:
            revived_suffixes.discard(identity[2])
        if save_dismissed_agents(self._dismissed_agents):
            try:
                sync_dismissed_agent_artifact_index(
                    self._dismissed_agents, added={identity}
                )
            except Exception:
                pass

    def _collect_dismissal_identities(self, agents: list[Agent]) -> set[AgentIdentity]:
        """Return identities hidden immediately after dismissing agents."""
        from ...models.agent import AgentType

        identities = {a.identity for a in agents}
        for agent in agents:
            identities.update(
                member.identity
                for member in clan_members_for_container(
                    agent,
                    self._agents_with_children,
                )
            )
            if (
                agent.agent_type == AgentType.WORKFLOW
                and not agent.is_workflow_child
                and agent.raw_suffix is not None
            ):
                for step in self._agents_with_children:
                    if (
                        step.is_workflow_child
                        and step.parent_timestamp == agent.raw_suffix
                        and step.parent_workflow == agent.workflow
                    ):
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
        self._dismissed_agent_objects = trim_dismissed_agent_objects(
            self._dismissed_agent_objects
        )
        if identities:
            self._bump_dismiss_revive_epoch()
