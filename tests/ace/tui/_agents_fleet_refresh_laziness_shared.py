"""Shared harness for the ``test_agents_fleet_refresh_laziness_*`` test modules.

Public helpers used by more than one split module live here under public
names so no new module imports a ``_``-prefixed name from another new
module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.ace.tui.actions.agents._fleet import AgentFleetMixin
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.fleet_agents import FleetRowsProjection
from sase.ace.tui.util.nav_gate import NavigationGate

__all__ = [
    "FleetRefreshHarness",
]


class FleetRefreshHarness(AgentFleetMixin):
    """Minimal Agents-tab host for exercising fleet refresh projection."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_local_with_children: list[Agent] = []
        self._agents_local_visible: list[Agent] = []
        self._agents_fleet_rows: list[Agent] = []
        self._agents_fleet_focus_rows: list[Agent] = []
        self._agents_fleet_applied_projection_signature = None
        self._agents_fleet_projection = FleetRowsProjection()
        self._agents_fleet_async_tasks: set[Any] = set()
        self._agents_fleet_refresh_generation = 1
        self._agents_fleet_loading = True
        self._agents_fleet_available = False
        self._agents_fleet_last_error = None
        self._agents_refresh_active_source = "unknown"
        self._agents_roster_generation = 0
        self._agents_removal_generation = 0
        self.header_updates = 0
        self.reproject_sources: list[str] = []
        self.attention_announcements: list[FleetRowsProjection] = []
        self._nav_gate = NavigationGate()
        self.timers: list[tuple[float, Callable[[], None]]] = []

    def _update_agents_header(self) -> None:
        self.header_updates += 1

    def _reproject_agents_from_current_mode(
        self,
        *,
        source: str,
        force: bool = False,
        selected_identity: object | None = None,
    ) -> None:
        super()._reproject_agents_from_current_mode(
            source=source,
            force=force,
            selected_identity=selected_identity,  # type: ignore[arg-type]
        )

    def _finalize_agent_list(self, *_args: object, **_kwargs: object) -> None:
        self.reproject_sources.append(self._agents_refresh_active_source)
        self._agents = list(self._agents_with_children)

    def _fleet_rows_with_dispatch_provisionals(
        self,
        rows: list[Agent],
    ) -> list[Agent]:
        return super()._fleet_rows_with_dispatch_provisionals(rows)

    def notify(self, *_args: object, **_kwargs: object) -> None:
        pass

    def _announce_remote_attention(self, projection: FleetRowsProjection) -> None:
        self.attention_announcements.append(projection)

    def set_timer(self, delay: float, callback: Callable[[], None]) -> None:
        self.timers.append((delay, callback))
