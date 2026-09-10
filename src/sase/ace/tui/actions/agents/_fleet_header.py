"""Header and status text for the unified Agents list."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static

from ...models.fleet_agents import FleetRowsProjection
from ._fleet_common import (
    agent_counts_as_active,
    local_machine_label,
    unified_attention_count,
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

        if not self._fleet_mode_available() and not getattr(  # type: ignore[attr-defined]
            self,
            "_agents_fleet_loading",
            False,
        ):
            header.add_class("hidden")
            return
        header.remove_class("hidden")
        status.update(self._unified_agents_status_text())

    def _unified_agents_status_text(self) -> str:
        prefix = f"here: {local_machine_label()}"
        if getattr(self, "_agents_fleet_loading", False):
            return f"{prefix} · loading machines..."
        error = getattr(self, "_agents_fleet_last_error", None)
        if error:
            return f"{prefix} · {error}"
        projection = getattr(self, "_agents_fleet_projection", FleetRowsProjection())
        rows = list(
            getattr(self, "_agents", [])
        ) or self._agents_source_for_current_mode(  # type: ignore[attr-defined]
            list(getattr(self, "_agents_local_with_children", []))
        )
        active_count = sum(1 for agent in rows if agent_counts_as_active(agent))
        attention_count = unified_attention_count(rows)
        host_count = projection.configured_host_count
        parts = [prefix, f"{active_count} active"]
        if attention_count:
            parts.append(f"{attention_count} needs you")
        if host_count:
            suffix = "machine" if host_count == 1 else "machines"
            parts.append(f"{host_count} {suffix}")
        diagnostic_text = unified_diagnostic_text(projection)
        if diagnostic_text:
            parts.append(diagnostic_text)
        elif projection.partial:
            parts.append("partial")
        return " · ".join(parts)


__all__ = ["AgentFleetHeaderMixin"]
