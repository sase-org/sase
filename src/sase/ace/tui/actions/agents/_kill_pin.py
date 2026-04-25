"""Agent kill, dismiss, and pin actions for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_groups import GroupRow

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentKillPinMixin:
    """Mixin providing agent kill, dismiss, and pin actions.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _pinned_agents: set[tuple[AgentType, str, str | None]]
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

        # Phase 5: focused group banner → bulk kill/dismiss every agent
        # in the group.  Marks take priority above; without marks the
        # banner focus drives a single-confirm bulk action.
        if self._current_group_key is not None:
            group = self._get_focused_group()  # type: ignore[attr-defined]
            if group is not None:
                self._bulk_kill_group_agents(group)  # type: ignore[attr-defined]
                return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        # Handle completed agents with dismiss (no confirmation needed)
        from ._core import DISMISSABLE_STATUSES

        if agent.status in DISMISSABLE_STATUSES:
            # Pinned agents: unpin first instead of dismissing directly
            if agent.identity in self._pinned_agents:
                self._unpin_and_focus(agent)
                return
            self._dismiss_done_agent(agent)  # type: ignore[attr-defined]
            return

        if agent.pid is None:
            # No process to kill - just dismiss the agent
            self._dismiss_done_agent(agent)  # type: ignore[attr-defined]
            return

        # Build description for confirmation dialog
        desc_parts = [f"Type: {agent.agent_type.value}"]
        desc_parts.append(f"CL: {agent.cl_name}")
        if agent.workspace_num is not None:
            desc_parts.append(f"Workspace: #{agent.workspace_num}")
        desc_parts.append(f"PID: {agent.pid}")
        agent_description = "\n".join(desc_parts)

        # Show confirmation modal
        from ...modals import ConfirmKillModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_kill_agent(agent)  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def action_pin_agent(self) -> None:
        """Toggle pinned state on an agent."""
        if self.current_tab != "agents":
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        if agent.raw_suffix is None:
            self.notify("Cannot pin agent: no timestamp", severity="warning")  # type: ignore[attr-defined]
            return

        from ....pinned_agents import save_pinned_agents, toggle_pinned_agent

        now_pinned = toggle_pinned_agent(self._pinned_agents, agent.identity)
        save_pinned_agents(self._pinned_agents)

        label = "Pinned" if now_pinned else "Unpinned"
        self.notify(f"{label} {agent.display_name}")  # type: ignore[attr-defined]

        # Rebuild panel indices so the item moves to the correct panel
        self._build_panel_indices()  # type: ignore[attr-defined]

        # Follow the item to its new panel (only if agent is already dismissable,
        # since running pinned agents stay in the main panel)
        from ._core import DISMISSABLE_STATUSES

        if agent.status in DISMISSABLE_STATUSES:
            if now_pinned and self._pinned_panel_focused != "pinned":  # type: ignore[has-type]
                self._pinned_panel_focused = "pinned"  # type: ignore[has-type]
            elif not now_pinned and self._pinned_panel_focused != "main":  # type: ignore[has-type]
                self._pinned_panel_focused = "main"  # type: ignore[has-type]

        # Auto-fallback if pinned panel is now empty
        if not self._pinned_panel_indices and self._pinned_panel_focused == "pinned":  # type: ignore[attr-defined, has-type]
            self._pinned_panel_focused = "main"  # type: ignore[has-type]

        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _get_focused_group(self) -> GroupRow | None:
        """Return the ``GroupRow`` matching ``_current_group_key``, if any.

        Rebuilds the grouping tree at the current fold level and looks up
        the first banner whose ``group_key`` equals ``_current_group_key``
        — the focused-banner key is always populated by the selection
        flow when a banner is the active row.  Returns ``None`` when no
        banner is focused or the key no longer maps to a visible group
        (e.g. the underlying agents have all been dismissed).
        """
        from ...models.agent_groups import build_agent_tree

        if self._current_group_key is None or not self._agents:
            return None
        level = self._group_fold_state.level  # type: ignore[attr-defined]
        for entry in build_agent_tree(self._agents, group_fold_level=level):
            if entry.kind != "group" or entry.group is None:
                continue
            if entry.group.group_key == self._current_group_key:
                return entry.group
        return None

    def _bulk_kill_group_agents(self, group: GroupRow) -> None:
        """Kill / dismiss every (top-level) agent in *group*.

        Routes through the same ``_present_bulk_kill_modal`` flow as the
        marked-set path so the user sees the same confirmation modal,
        per-agent listing, and kill/dismiss split.  Workflow children are
        excluded — killing a parent cascades to its children via
        ``_collect_immediate_kill_identities``, so listing them here
        would only inflate the modal.
        """
        identities = set()
        for idx in group.agent_indices:
            if 0 <= idx < len(self._agents):
                a = self._agents[idx]
                if a.is_workflow_child:
                    continue
                identities.add(a.identity)
        agents = [a for a in self._agents_with_children if a.identity in identities]
        if not agents:
            self.notify("No agents in group", severity="warning")  # type: ignore[attr-defined]
            return

        from ...models.agent_groups import banner_label

        label = banner_label(group)
        count = len(agents)
        plural = "s" if count != 1 else ""
        header = f"Group: {label} ({count} agent{plural})"
        self._present_bulk_kill_modal(agents, header=header)  # type: ignore[attr-defined]

    def _unpin_and_focus(self, agent: Agent) -> None:
        """Unpin an agent and follow it to the main panel."""
        from ....pinned_agents import save_pinned_agents, toggle_pinned_agent

        toggle_pinned_agent(self._pinned_agents, agent.identity)
        save_pinned_agents(self._pinned_agents)

        self._build_panel_indices()  # type: ignore[attr-defined]
        self._pinned_panel_focused = "main"  # type: ignore[has-type]

        # Find the agent's new position in the main panel
        main_indices: list[int] = self._main_panel_indices  # type: ignore[attr-defined]
        for i, idx in enumerate(main_indices):
            if self._agents[idx] is agent:
                self.current_idx = i
                break

        # Auto-fallback if pinned panel is now empty
        if not self._pinned_panel_indices and self._pinned_panel_focused == "pinned":  # type: ignore[attr-defined, has-type]
            self._pinned_panel_focused = "main"  # type: ignore[has-type]

        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        self.notify(f"Unpinned {agent.display_name}")  # type: ignore[attr-defined]
