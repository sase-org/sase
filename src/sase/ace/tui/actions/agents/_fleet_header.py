"""Header and status text for Agents Focus/Fleet mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static

from ...models.fleet_agents import FleetRowsProjection
from ...widgets.panel_tab_strip import PanelTab, PanelTabStrip
from ._fleet_common import (
    agent_counts_as_active,
    local_machine_label,
    unified_agents_enabled,
    unified_attention_count,
    unified_diagnostic_text,
)

if TYPE_CHECKING:
    from ...app import AgentsSubTab


class AgentFleetHeaderMixin:
    """Update the Agents header for Focus/Fleet state."""

    if TYPE_CHECKING:
        current_agents_subtab: AgentsSubTab

    def _update_agents_header(self) -> None:
        try:
            header = self.query_one("#agents-header")  # type: ignore[attr-defined]
            tabs = self.query_one("#agents-mode-tabs", PanelTabStrip)  # type: ignore[attr-defined]
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
        if unified_agents_enabled():
            tabs.add_class("hidden")
            status.update(self._unified_agents_status_text())
            return
        tabs.remove_class("hidden")
        counts = dict(
            getattr(self, "_agents_fleet_projection", FleetRowsProjection()).counts
        )
        local_count = counts.get(
            "local",
            len(getattr(self, "_agents_local_with_children", [])),
        )
        focus_total = counts.get(
            "focus_total",
            int(local_count) + len(getattr(self, "_agents_fleet_focus_rows", [])),
        )
        fleet_count = counts.get(
            "fleet",
            len(getattr(self, "_agents_fleet_rows", [])),
        )
        tabs.set_tabs(
            (
                PanelTab(
                    "focus",
                    f"Focus {focus_total}",
                    "#5FD7FF",
                    compact_label=f"Focus {focus_total}",
                    micro_label="F",
                    icon="●",
                ),
                PanelTab(
                    "fleet",
                    f"Fleet {fleet_count}",
                    "#D7AF5F",
                    compact_label=f"Fleet {fleet_count}",
                    micro_label="L",
                    icon="◆",
                ),
            ),
            active_tab=self.current_agents_subtab,
        )
        status.update(self._fleet_status_text())

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

    def _fleet_status_text(self) -> str:
        if getattr(self, "_agents_fleet_loading", False):
            return "loading fleet..."
        error = getattr(self, "_agents_fleet_last_error", None)
        if error:
            return error
        projection = getattr(self, "_agents_fleet_projection", FleetRowsProjection())
        issue_count = len(projection.diagnostics)
        host_count = projection.configured_host_count
        raw_fleet_count = projection.counts.get("fleet")
        fleet_count = (
            raw_fleet_count
            if isinstance(raw_fleet_count, int)
            else len(projection.fleet_rows)
        )
        partial = bool(projection.partial)
        if issue_count:
            suffix = "issue" if issue_count == 1 else "issues"
            text = f"{issue_count} {suffix}"
            if partial:
                text = f"{text} · partial"
            return text
        if host_count:
            suffix = "machine" if host_count == 1 else "machines"
            text = f"{host_count} {suffix}"
            if partial:
                text = f"{text} · partial"
            if self.current_agents_subtab == "fleet" and fleet_count == 0:
                text = f"{text} · 0 results"
            return text
        if partial:
            return "partial"
        return ""


__all__ = ["AgentFleetHeaderMixin"]
