"""Header and status text for the unified Agents list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static

from ...models.fleet_agents import FleetRowsProjection
from ._fleet_common import (
    host_feed_issue_text,
    unified_diagnostic_text,
)

if TYPE_CHECKING:
    from ...app import AgentsSubTab


class AgentFleetHeaderMixin:
    """Update the Agents header for unified fleet state."""

    if TYPE_CHECKING:
        current_agents_subtab: AgentsSubTab

    def _update_agents_header(self) -> None:
        try:
            header = self.query_one("#agents-header")  # type: ignore[attr-defined]
            status = self.query_one("#agents-fleet-status", Static)  # type: ignore[attr-defined]
        except Exception:
            return

        if not self._fleet_mode_available():  # type: ignore[attr-defined]
            header.add_class("hidden")
            return
        text = self._agents_fleet_problem_text()
        if not text:
            header.add_class("hidden")
            return
        header.remove_class("hidden")
        status.update(text)

    def _agents_fleet_problem_text(self) -> str:
        error = getattr(self, "_agents_fleet_last_error", None)
        if error:
            return str(error)
        projection = getattr(self, "_agents_fleet_projection", FleetRowsProjection())
        parts: list[str] = []
        diagnostic_text = unified_diagnostic_text(projection)
        if diagnostic_text:
            parts.append(diagnostic_text)
        host_issue_text = host_feed_issue_text(projection)
        if host_issue_text:
            parts.append(host_issue_text)
        return " · ".join(parts)


__all__ = ["AgentFleetHeaderMixin"]
