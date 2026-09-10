"""Focus/Fleet tab actions and row projection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import on

from ...widgets.panel_tab_strip import PanelTabStrip
from ._fleet_common import _AGENTS_SUBTABS, unified_agents_enabled

if TYPE_CHECKING:
    from ...app import AgentsSubTab
    from ...models import Agent
    from ...models.agent import AgentType


class AgentFleetProjectionMixin:
    """Focus/Fleet mode switching and row reprojection."""

    if TYPE_CHECKING:
        current_agents_subtab: AgentsSubTab
        current_tab: str
        current_idx: int
        _agents: list[Agent]
        _agents_with_children: list[Agent]
        _agents_local_with_children: list[Agent]
        _agents_local_visible: list[Agent]
        _agents_fleet_rows: list[Agent]
        _agents_fleet_focus_rows: list[Agent]
        _agents_refresh_active_source: str

    @on(PanelTabStrip.TabClicked)
    def _on_agents_mode_tab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        if event.tab_id not in _AGENTS_SUBTABS:
            return
        event.stop()
        if unified_agents_enabled():
            return
        self._set_agents_subtab(event.tab_id)

    def watch_current_agents_subtab(
        self,
        old_mode: AgentsSubTab,
        new_mode: AgentsSubTab,
    ) -> None:
        """Reproject cached Agents rows when Focus/Fleet mode changes."""
        if old_mode == new_mode:
            return
        if unified_agents_enabled():
            if new_mode == "fleet":
                self.current_agents_subtab = "focus"
                return
            self._reproject_agents_from_current_mode(source="mode_switch")
            self._schedule_agents_fleet_refresh(  # type: ignore[attr-defined]
                source="mode_switch",
                force=True,
            )
            return
        if new_mode == "fleet" and not self._fleet_mode_available():  # type: ignore[attr-defined]
            self.current_agents_subtab = "focus"
            self.notify("Fleet view is not configured")  # type: ignore[attr-defined]
            return
        self._reproject_agents_from_current_mode(source="mode_switch")
        self._schedule_agents_fleet_refresh(  # type: ignore[attr-defined]
            source="mode_switch",
            force=new_mode == "fleet",
        )

    def action_cycle_agents_subtab(self) -> None:
        """Cycle between Focus and Fleet agent modes."""
        self._cycle_agents_subtab(reverse=False)

    def action_cycle_agents_subtab_reverse(self) -> None:
        """Cycle between Focus and Fleet agent modes in reverse."""
        self._cycle_agents_subtab(reverse=True)

    def action_view_agent_in_focus(self) -> None:
        """Switch to Focus mode on the selected followed remote row."""
        if unified_agents_enabled():
            self.notify("Remote agents are already in the unified Agents list")  # type: ignore[attr-defined]
            return
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None or not getattr(agent, "fleet_origin_alias", None):
            self.notify("Select a remote fleet agent")  # type: ignore[attr-defined]
            return
        if not getattr(agent, "fleet_followed", False):
            self.notify("Follow the remote agent before viewing it in Focus")  # type: ignore[attr-defined]
            return
        identity = agent.identity
        self.current_agents_subtab = "focus"
        self._select_agent_identity_after_projection(identity)

    def action_connect_agent_machine(self) -> None:
        """Open the persistent Machines administration pane."""
        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener("machines")

    def action_setup_agent_machine(self) -> None:
        """Open enrollment guidance while no remote machine is configured."""
        fleet_mode_available = getattr(self, "_fleet_mode_available", None)
        if callable(fleet_mode_available) and fleet_mode_available():
            self.notify(  # type: ignore[attr-defined]
                "Remote machines are already enrolled; run 'sase machine init' "
                "to rescan, or 'sase machine list' / 'sase machine status' "
                "from a shell for details"
            )
            return
        opener = getattr(self, "_open_config_center", None)
        if callable(opener):
            opener("machines")
            return
        visible_after_enrollment = (
            "The Agents list includes it once a machine is enrolled."
            if unified_agents_enabled()
            else "The Focus/Fleet strip appears once a machine is enrolled."
        )
        self.notify(  # type: ignore[attr-defined]
            "No remote machines are enrolled. On the target, run "
            "'sase machine bootstrap --json' into a protected file. On this "
            "controller, run 'sase machine init -B <file>' to discover, enroll, "
            f"and verify. {visible_after_enrollment}",
            timeout=12,
        )

    def _cycle_agents_subtab(self, *, reverse: bool) -> None:
        if unified_agents_enabled():
            self.notify("Agents already includes enrolled machines")  # type: ignore[attr-defined]
            return
        if not self._fleet_mode_available():  # type: ignore[attr-defined]
            self.notify("Fleet view is not configured")  # type: ignore[attr-defined]
            return
        current = self.current_agents_subtab
        if reverse:
            next_mode = "focus" if current == "fleet" else "fleet"
        else:
            next_mode = "fleet" if current == "focus" else "focus"
        self._set_agents_subtab(next_mode)

    def _set_agents_subtab(self, mode: str) -> None:
        if unified_agents_enabled():
            self.current_agents_subtab = "focus"
            return
        self.current_agents_subtab = "fleet" if mode == "fleet" else "focus"

    def _project_agents_for_current_mode_after_load(
        self,
        local_unfiltered: list[Agent],
        local_visible: list[Agent],
    ) -> tuple[list[Agent], list[Agent]]:
        self._agents_local_with_children = list(local_unfiltered)
        self._agents_local_visible = list(local_visible)
        return (
            self._agents_source_for_current_mode(local_unfiltered),
            self._agents_source_for_current_mode(local_visible),
        )

    def _sync_agents_local_source_from_current(self) -> None:
        """Mirror local-only rows after existing in-memory mutations."""
        if self.current_agents_subtab == "fleet" and not unified_agents_enabled():
            return
        self._agents_local_with_children = self._local_agents_from_mixed(
            getattr(self, "_agents_with_children", [])
        )
        self._agents_local_visible = self._local_agents_from_mixed(
            getattr(self, "_agents", [])
        )

    def _agents_source_for_current_mode(self, local_agents: list[Agent]) -> list[Agent]:
        fleet_rows = self._fleet_rows_with_dispatch_provisionals(  # type: ignore[attr-defined]
            list(getattr(self, "_agents_fleet_rows", []))
        )
        focus_rows = self._fleet_rows_with_dispatch_provisionals(  # type: ignore[attr-defined]
            list(getattr(self, "_agents_fleet_focus_rows", []))
        )
        if unified_agents_enabled():
            return [
                *local_agents,
                *fleet_rows,
            ]
        if self.current_agents_subtab == "fleet":
            return fleet_rows
        return [
            *local_agents,
            *focus_rows,
        ]

    @staticmethod
    def _local_agents_from_mixed(agents: list[Agent]) -> list[Agent]:
        return [
            agent for agent in agents if not getattr(agent, "fleet_origin_alias", None)
        ]

    def _reproject_agents_from_current_mode(
        self,
        *,
        source: str,
        selected_identity: tuple[AgentType, str, str | None] | None = None,
    ) -> None:
        if selected_identity is None and 0 <= self.current_idx < len(self._agents):
            selected_identity = self._agents[self.current_idx].identity
        previous_agents = list(getattr(self, "_agents", []))
        local_cache = getattr(self, "_agents_local_with_children", None)
        if local_cache is None:
            local_base = [
                agent
                for agent in getattr(self, "_agents_with_children", [])
                if not getattr(agent, "fleet_origin_alias", None)
            ]
        else:
            local_base = list(local_cache)
        self._agents_with_children = self._agents_source_for_current_mode(local_base)
        self._agents = list(self._agents_with_children)
        self._agents_refresh_active_source = source  # type: ignore[attr-defined]
        try:
            self._finalize_agent_list(  # type: ignore[attr-defined]
                self.current_tab == "agents",
                selected_identity,
                save_unfiltered=False,
                previous_agents=previous_agents,
            )
        finally:
            self._agents_refresh_active_source = "unknown"  # type: ignore[attr-defined]
        self._update_agents_header()  # type: ignore[attr-defined]

    def _select_agent_identity_after_projection(
        self,
        identity: tuple[AgentType, str, str | None],
    ) -> None:
        for index, agent in enumerate(getattr(self, "_agents", [])):
            if agent.identity == identity:
                self.current_idx = index
                return

    def _fleet_mode_available(self) -> bool:
        return bool(
            getattr(self, "_agents_fleet_available", False)
            or getattr(self, "_agents_fleet_rows", ())
            or getattr(self, "_agents_fleet_focus_rows", ())
            or getattr(self, "_agents_dispatch_provisional_rows", {})
        )


__all__ = ["AgentFleetProjectionMixin"]
