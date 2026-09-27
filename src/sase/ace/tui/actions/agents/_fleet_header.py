"""Header and status text for the unified Agents list."""

from __future__ import annotations

from textual.widgets import Static

from ...models.fleet_agents import FleetRowsProjection
from ._fleet_common import (
    host_feed_issue_text,
    unified_diagnostic_text,
)


class AgentFleetHeaderMixin:
    """Update the Agents header for unified fleet state."""

    def _update_agents_header(self) -> None:
        try:
            header = self.query_one("#agents-header")  # type: ignore[attr-defined]
            status = self.query_one("#agents-fleet-status", Static)  # type: ignore[attr-defined]
        except Exception:
            return

        # Minimal agent-tab strip (tab-state-keys phase): the row shows when
        # the strip is visible or a diagnostic exists. With the flag off the
        # strip predicate is always False, so the flag-off path below is
        # byte-identical to the pre-tabs behavior.
        strip_visible = False
        try:
            from ...agent_tabs_flag import agent_tabs_enabled
            from ._agent_tabs import strip_visible_for_owner

            strip_visible = bool(agent_tabs_enabled() and strip_visible_for_owner(self))
        except Exception:
            strip_visible = False
        if not self._fleet_mode_available():  # type: ignore[attr-defined]
            if not strip_visible:
                header.add_class("hidden")
                return
            status.update("")
        else:
            text = self._agents_fleet_problem_text()
            if not text and not strip_visible:
                header.add_class("hidden")
                return
            status.update(text)
        header.remove_class("hidden")
        try:
            from ...widgets.panel_tab_strip import PanelTabStrip

            strip = self.query_one("#agents-tab-strip", PanelTabStrip)  # type: ignore[attr-defined]
        except Exception:
            return
        if strip_visible:
            strip.remove_class("hidden")
        else:
            strip.add_class("hidden")
        refresh_strip = getattr(self, "_refresh_agent_tab_strip", None)
        if callable(refresh_strip):
            try:
                refresh_strip()
            except Exception:
                pass

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
