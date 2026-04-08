"""Agent kill, dismiss, and pin actions for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentKillPinMixin:
    """Mixin providing agent kill, dismiss, and pin actions.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _pinned_agents: set[tuple[AgentType, str, str | None]]

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
