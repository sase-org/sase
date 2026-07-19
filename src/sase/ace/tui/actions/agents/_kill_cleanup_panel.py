"""Cleanup-panel shell and shared cleanup helpers for agent kill actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...modals import AgentCleanupAction, AgentCleanupPanelState
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire


class AgentCleanupPanelMixin:
    """Mixin for the cleanup panel and cleanup target planning helpers."""

    current_tab: str
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    def action_open_agent_cleanup_panel(self) -> None:
        """Open the Agents cleanup panel, or clear output on the AXE tab."""
        if self.current_tab == "axe":
            self.action_clear_axe_output()  # type: ignore[attr-defined]
            return
        if self.current_tab != "agents":
            return

        from ...modals import AgentCleanupModal, AgentCleanupResult

        def on_dismiss(result: AgentCleanupResult | None) -> None:
            if result is None:
                return
            self._run_agent_cleanup_panel_action(result.action)

        self.push_screen(  # type: ignore[attr-defined]
            AgentCleanupModal(self._build_agent_cleanup_panel_state()),
            on_dismiss,
        )

    def _build_agent_cleanup_panel_state(self) -> AgentCleanupPanelState:
        """Build count state for the cleanup panel shell."""
        from ._core import DISMISSABLE_STATUSES
        from ...modals import AgentCleanupPanelState

        panel_agents = self._agents_in_focused_panel()  # type: ignore[attr-defined]
        all_agents = list(self._agents)
        clans = self._agent_cleanup_clans_in_focused_panel(panel_agents)  # type: ignore[attr-defined]
        clan_targets = self._agent_cleanup_targets_from_candidates(panel_agents)
        clan_target_wires = None
        cleanable_clans: list[Agent] = []
        if clans:
            from sase.core.agent_cleanup_facade import agents_to_cleanup_targets

            clan_target_wires = agents_to_cleanup_targets(clan_targets)
            for clan in clans:
                plan = self._plan_clan_cleanup_container(  # type: ignore[attr-defined]
                    clan,
                    clan_targets,
                    target_wires=clan_target_wires,
                )
                if plan.kill_items or plan.dismiss_items:
                    cleanable_clans.append(clan)

        def running_count(agents: list[Agent]) -> int:
            return sum(
                1
                for agent in agents
                if agent.pid is not None and agent.status not in DISMISSABLE_STATUSES
            )

        def completed_count(agents: list[Agent]) -> int:
            return sum(
                1
                for agent in agents
                if agent.status in DISMISSABLE_STATUSES and agent.raw_suffix is not None
            )

        def failed_count(agents: list[Agent]) -> int:
            return sum(1 for agent in agents if agent.status == "FAILED")

        group_count = 0
        group = self._get_focused_group()  # type: ignore[attr-defined]
        if group is not None:
            group_count = sum(
                1
                for idx in group.agent_indices
                if 0 <= idx < len(self._agents)
                and not self._agents[idx].is_workflow_child
            )

        return AgentCleanupPanelState(
            focused_panel_label=self._focused_panel_label(),
            panel_running_count=running_count(panel_agents),
            panel_completed_count=completed_count(panel_agents),
            panel_failed_count=failed_count(panel_agents),
            all_running_count=running_count(all_agents),
            all_completed_count=completed_count(all_agents),
            all_failed_count=failed_count(all_agents),
            marked_count=len(self._marked_agents),
            group_count=group_count,
            tribe_count=len(self._known_agent_cleanup_tribes()),
            clan_count=len(cleanable_clans),
            focused_clan_label=self._focused_cleanup_clan_label(clans),  # type: ignore[attr-defined]
        )

    def _run_agent_cleanup_panel_action(self, action: AgentCleanupAction) -> None:
        """Route a selected cleanup panel action through existing operations."""
        if action == "dismiss_panel_done":
            self._dismiss_all_done_agents()  # type: ignore[attr-defined]
            return
        if action == "dismiss_all_done":
            self._dismiss_all_done_agents_global()  # type: ignore[attr-defined]
            return
        if action == "kill_panel":
            self._kill_and_dismiss_all_agents()  # type: ignore[attr-defined]
            return
        if action == "kill_all":
            self._kill_and_dismiss_all_agents_global()  # type: ignore[attr-defined]
            return
        if action == "marked":
            self._bulk_kill_marked_agents()  # type: ignore[attr-defined]
            return
        if action == "group":
            group = self._get_focused_group()  # type: ignore[attr-defined]
            if group is None:
                self.notify("No focused group", severity="warning")  # type: ignore[attr-defined]
                return
            self._bulk_kill_group_agents(group)  # type: ignore[attr-defined]
            return
        if action == "tribe":
            self._open_tribe_cleanup_selector()  # type: ignore[attr-defined]
            return
        if action == "clan":
            self._open_clan_cleanup_selector()  # type: ignore[attr-defined]
            return
        if action == "custom":
            self._open_custom_cleanup_selector()  # type: ignore[attr-defined]
            return
        self.notify("Cleanup option is not available yet", severity="warning")  # type: ignore[attr-defined]

    def _focused_panel_label(self) -> str:
        from ...models.agent_panels import agent_panel_label

        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return "all panels"
        return agent_panel_label(panel_group.focused_key)

    def _agent_cleanup_current_scope_targets(self) -> list[Agent]:
        """Return cleanup targets scoped to the current Agents-tab list."""
        return self._agent_cleanup_targets_from_candidates(list(self._agents))

    def _agent_cleanup_targets_from_candidates(
        self, candidates: list[Agent]
    ) -> list[Agent]:
        """Expand loaded cleanup candidates without leaving their panel scope.

        Synthetic clan rows expand to their real generation members, and loaded
        workflow children are included when their parent is a candidate. Identity
        de-duplication preserves the cached Agents-tab order and keeps this helper
        safe for both the cleanup panel and collapsed-panel ``x`` action.
        """
        from ...models.agent import AgentType

        targets: list[Agent] = []
        seen: set[tuple[AgentType, str, str | None]] = set()
        parent_timestamps: set[str] = set()

        def add(agent: Agent) -> None:
            if agent.is_clan_container:
                from ._clan_cleanup import clan_members_for_container

                for member in clan_members_for_container(
                    agent, self._agents_with_children
                ):
                    add(member)
                return
            if agent.identity in seen:
                return
            seen.add(agent.identity)
            targets.append(agent)
            if (
                agent.agent_type == AgentType.WORKFLOW
                and not agent.is_workflow_child
                and agent.raw_suffix is not None
            ):
                parent_timestamps.add(agent.raw_suffix)

        for agent in candidates:
            add(agent)
        for agent in self._agents_with_children:
            if agent.is_workflow_child and agent.parent_timestamp in parent_timestamps:
                add(agent)
        return targets

    def _known_agent_cleanup_tribes(self) -> tuple[str, ...]:
        """Return tribe names present in the current Agents-tab list."""
        from ...models.agent_panels import (
            DEFAULT_AGENT_TRIBE,
            effective_tribe_per_agent,
        )

        tribes = {
            tribe
            for tribe in effective_tribe_per_agent(self._agents)
            if tribe != DEFAULT_AGENT_TRIBE
        }
        return tuple(sorted(tribes, key=str.lower))

    def _present_planned_cleanup(
        self,
        request: object,
        *,
        header: str,
        targets: list[Agent] | None = None,
    ) -> None:
        """Preview and confirm a planner-backed cleanup request."""
        from sase.core.agent_cleanup_facade import (
            agent_to_cleanup_target,
            agents_to_cleanup_targets,
            plan_agent_cleanup,
        )

        cleanup_targets = list(
            self._agents_with_children if targets is None else targets
        )
        cleanup_targets = [
            agent for agent in cleanup_targets if not agent.is_clan_container
        ]
        plan = plan_agent_cleanup(agents_to_cleanup_targets(cleanup_targets), request)  # type: ignore[arg-type]
        by_wire_identity = {
            agent_to_cleanup_target(agent).identity: agent for agent in cleanup_targets
        }
        killable = [
            by_wire_identity[item.identity]
            for item in plan.kill_items
            if item.identity in by_wire_identity
        ]
        dismissable = [
            by_wire_identity[item.identity]
            for item in plan.dismiss_items
            if item.identity in by_wire_identity
        ]
        if not killable and not dismissable:
            self.notify("No selected agents can be cleaned up", severity="warning")  # type: ignore[attr-defined]
            return
        self._present_bulk_kill_modal(  # type: ignore[attr-defined]
            [*killable, *dismissable],
            header=header,
        )

    def _notify_no_focused_cleanup_action(
        self, plan: AgentCleanupPlanWire | None, agent: Agent | None = None
    ) -> None:
        skipped_items = getattr(plan, "skipped_items", ()) if plan is not None else ()
        focused_identity = None
        if agent is not None:
            focused_identity = (
                agent.agent_type.value,
                agent.cl_name,
                agent.raw_suffix,
            )
        skipped = None
        if focused_identity is not None:
            skipped = next(
                (
                    item
                    for item in skipped_items
                    if (
                        item.identity.agent_type,
                        item.identity.cl_name,
                        item.identity.raw_suffix,
                    )
                    == focused_identity
                ),
                None,
            )
        if skipped is None:
            skipped = next(iter(skipped_items), None)
        if skipped is None:
            self.notify("No selected agents can be cleaned up", severity="warning")  # type: ignore[attr-defined]
            return
        detail = f": {skipped.detail}" if skipped.detail else ""
        self.notify(  # type: ignore[attr-defined]
            f"Agent cannot be cleaned up ({skipped.reason}{detail})",
            severity="warning",
        )
