"""Focused-agent, panel, and group kill action dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._panel_fold_intent import panel_is_collapsed

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_groups import GroupRow
    from ...models.agent_tribe_summary import (
        AgentPanelFocus,
        CollapsedAgentPanelFocus,
    )

TabName = Literal["changespecs", "agents", "axe"]


class AgentKillActionFlowMixin:
    """Mixin dispatching the kill key for focused agent scopes."""

    current_tab: TabName
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _current_group_key: tuple[str, ...] | None

    def action_kill_agent(self) -> None:
        """Kill or dismiss agent, or toggle/kill axe on AXE tab."""
        if self.current_tab == "changespecs":
            self.action_toggle_hide_submitted()  # type: ignore[attr-defined]
            return
        if self.current_tab == "axe":
            self._toggle_or_kill_axe_view()  # type: ignore[attr-defined]
            return
        if self.current_tab != "agents":
            return

        # Bulk mode: if any marks exist, kill/dismiss the full marked set.
        if self._marked_agents:
            self._bulk_kill_marked_agents()  # type: ignore[attr-defined]
            return

        # A whole panel is an explicit bulk-cleanup selection. The
        # backing ``current_idx`` remains only an expansion anchor and must
        # never fall through to the single-agent path.
        panel_focus = self._resolve_panel_cleanup_focus()
        if panel_focus is not None:
            self._bulk_kill_panel_agents(panel_focus)
            return

        # A focused group banner applies the bulk action to the whole group.
        if self._current_group_key is not None:
            group = self._get_focused_group()
            if group is not None:
                self._bulk_kill_group_agents(group)
                return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.is_clan_container:
            from ._clan_cleanup import clan_members_for_container

            members = clan_members_for_container(
                agent,
                self._agents_with_children,
            )
            if not members:
                self.notify("No agents remain in clan", severity="warning")  # type: ignore[attr-defined]
                return
            self._present_bulk_kill_modal(  # type: ignore[attr-defined]
                members,
                header=f"Clan: {agent.agent_clan}",
            )
            return

        cleanup_plan = self._plan_focused_agent_cleanup(agent)  # type: ignore[attr-defined]
        if cleanup_plan.dismiss_items and not cleanup_plan.kill_items:
            self._dismiss_planned_agent(agent, cleanup_plan)  # type: ignore[attr-defined]
            return

        if not cleanup_plan.kill_items:
            self._notify_no_focused_cleanup_action(  # type: ignore[attr-defined]
                cleanup_plan, agent
            )
            return

        from ._confirmation_lanes import (
            confirmation_lane_entries,
            format_confirmation_entries,
        )

        desc_parts = ["Agent lane:"]
        desc_parts.extend(
            format_confirmation_entries(
                confirmation_lane_entries(
                    [agent],
                    self._agents_with_children,
                    include_running_family_members=True,
                )
            )
        )
        desc_parts.append(f"Type: {agent.agent_type.value}")
        if agent.workspace_num is not None:
            desc_parts.append(f"Workspace: #{agent.workspace_num}")
        desc_parts.append(f"PID: {agent.pid}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmKillModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_kill_agent(agent, cleanup_plan)  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def _resolve_panel_cleanup_focus(self) -> AgentPanelFocus | None:
        """Resolve panel focus while preserving collapsed-only test adapters."""
        collapsed_resolver = getattr(self, "_resolve_focused_collapsed_panel", None)
        collapsed_focus = collapsed_resolver() if callable(collapsed_resolver) else None
        if collapsed_focus is not None:
            return collapsed_focus

        panel_group = getattr(self, "_panel_group", None)
        if panel_group is not None and panel_is_collapsed(
            self, panel_group.focused_key
        ):
            return None
        resolver = getattr(self, "_resolve_focused_panel", None)
        return resolver() if callable(resolver) else None

    def _bulk_kill_panel_agents(self, focus: AgentPanelFocus) -> None:
        """Confirm cleanup of the complete cached selected-panel membership."""
        live_focus = self._resolve_panel_cleanup_focus()
        scope = "Collapsed panel" if focus.collapsed else "Panel"
        if live_focus != focus:
            self.notify(  # type: ignore[attr-defined]
                f"{scope} focus changed; nothing cleaned up",
                severity="warning",
            )
            return

        panel_agents = list(
            self._agent_panel_index().slice_for(focus.panel_key).agents  # type: ignore[attr-defined]
        )
        if not panel_agents:
            self.notify(  # type: ignore[attr-defined]
                f"No agents remain in {scope.lower()}", severity="warning"
            )
            return

        live_identities = {agent.identity for agent in self._agents_with_children}
        if any(agent.identity not in live_identities for agent in panel_agents):
            self.notify(  # type: ignore[attr-defined]
                f"{scope} membership changed; nothing cleaned up",
                severity="warning",
            )
            return

        targets = self._agent_cleanup_targets_from_candidates(panel_agents)  # type: ignore[attr-defined]
        if not targets or self._resolve_panel_cleanup_focus() != focus:
            self.notify(  # type: ignore[attr-defined]
                f"{scope} membership changed; nothing cleaned up",
                severity="warning",
            )
            return

        from ...models.agent_panels import agent_panel_label

        label = agent_panel_label(focus.panel_key)
        self._present_bulk_kill_modal(  # type: ignore[attr-defined]
            targets,
            header=f"Panel: {label}",
        )

    def _bulk_kill_collapsed_panel_agents(
        self, focus: CollapsedAgentPanelFocus
    ) -> None:
        """Compatibility wrapper for collapsed-panel-only callers."""
        self._bulk_kill_panel_agents(focus)

    def _get_focused_group(self) -> GroupRow | None:
        """Return the ``GroupRow`` matching ``_current_group_key``, if any."""
        from ._group_focus import get_focused_agent_group

        return get_focused_agent_group(self)

    def _bulk_kill_group_agents(self, group: GroupRow) -> None:
        """Kill or dismiss every top-level agent in ``group``."""
        from ._group_focus import top_level_group_agents

        identities = {a.identity for a in top_level_group_agents(group, self._agents)}
        agents = [a for a in self._agents_with_children if a.identity in identities]
        if not agents:
            self.notify("No agents in group", severity="warning")  # type: ignore[attr-defined]
            return

        from ...models.agent_groups import banner_label

        label = banner_label(group)
        header = f"Group: {label}"
        self._present_bulk_kill_modal(agents, header=header)  # type: ignore[attr-defined]
