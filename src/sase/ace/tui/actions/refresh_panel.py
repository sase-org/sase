"""Refresh panel wiring behind the ``refresh_panel`` sunset flag."""

from __future__ import annotations

from typing import Literal

from sase.ace.tui.actions.event_refresh._freshness import (
    freshness_label,
    note_surface_refreshed,
    surface_refreshed_age,
)
from sase.ace.tui.modals.refresh_panel_modal import (
    RefreshChoice,
    RefreshPanelModal,
    RefreshRow,
)
from sase.feature_flags import FeatureFlag, current_flags
from sase.llm_provider.usage.refresh import UsageRefreshReceipt, submit_usage_refresh

TabName = Literal["artifacts", "agents", "axe"]

FULL_HISTORY_MIGRATION_BANNER = ",y lives here now — press f"
REFRESH_PANEL_COMMAND_LABEL = "Open Refresh panel"
REFRESH_TAB_COMMAND_LABEL = "Refresh tab"
_USAGE_DISABLED_MESSAGE = "subscription usage collection is disabled"
_USAGE_ALREADY_RUNNING = "Usage refresh already running"
_TAB_LABELS = {"agents": "Agents", "axe": "Axe"}


def refresh_panel_enabled() -> bool:
    """Return whether ``R`` and ``,y`` should open the Refresh panel."""
    return current_flags().enabled(FeatureFlag.refresh_panel)


class RefreshPanelMixin:
    """Build the Refresh panel and dispatch the chosen refresh."""

    current_tab: TabName
    _agents_history_reconcile_pending: bool
    _last_full_sanity_refresh: float

    def action_refresh(self) -> None:
        """Refresh the current tab, or open the Refresh panel when enabled."""
        if refresh_panel_enabled():
            RefreshPanelMixin._open_refresh_panel(self)
            return
        RefreshPanelMixin._refresh_current_tab_surfaces(self)
        self.notify("Refreshed")  # type: ignore[attr-defined]

    def action_refresh_agents_full_history(self) -> None:
        """Explicitly refresh Agents from full artifact history."""
        RefreshPanelMixin._refresh_agents_full_history(self)
        self.notify("Refreshing Agents from full history")  # type: ignore[attr-defined]

    def _refresh_current_tab_surfaces(self) -> str:
        """Refresh the current tab's content and stamp freshness.

        Returns the tab label shown in the Refresh panel.
        """
        if self.current_tab == "agents":
            # Route through the async path so the UI returns immediately.
            # _apply_loaded_agents triggers _refresh_agent_file after the
            # background load completes. Normal refresh is always the
            # visible-inbox Tier 1 path; full-history scans are exposed
            # through ``action_refresh_agents_full_history`` instead.
            self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
                source="manual",
                full_history=False,
            )
            note_surface_refreshed(self, "agents")
            schedule_fleet_refresh = getattr(
                self,
                "_schedule_agents_fleet_refresh",
                None,
            )
            if callable(schedule_fleet_refresh):
                schedule_fleet_refresh(source="manual", force=True)
        elif self.current_tab == "artifacts":
            if getattr(self, "current_artifacts_subtab", "patches") == "patches":
                self._schedule_patches_async_refresh()  # type: ignore[attr-defined]
                note_surface_refreshed(self, "patches")
            else:
                self._request_active_artifacts_refresh()  # type: ignore[attr-defined]
                note_surface_refreshed(self, "artifacts")
        else:  # axe
            # Targeted refresh repaints the focused panel first; the
            # full-fleet refresh lands whenever it lands.
            self._schedule_targeted_axe_refresh()  # type: ignore[attr-defined]
            self._schedule_axe_async_refresh()  # type: ignore[attr-defined]
            note_surface_refreshed(self, "axe")
        return RefreshPanelMixin._refresh_tab_label(self)

    def _refresh_agents_full_history(self) -> None:
        """Schedule the Agents full-history rescan without a toast."""
        self._agents_history_reconcile_pending = False
        self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
            source="manual_full_history",
            full_history=True,
            full_history_reason="manual_full_history_refresh",
        )

    def _open_refresh_panel(
        self,
        *,
        initial_choice: RefreshChoice = "this_tab",
        banner: str | None = None,
    ) -> None:
        """Push the Refresh panel chooser."""
        modal = RefreshPanelModal(
            tab_label=RefreshPanelMixin._refresh_tab_label(self),
            rows=RefreshPanelMixin._refresh_panel_rows(self),
            auto_refresh_label=RefreshPanelMixin._auto_refresh_label(self),
            initial_choice=initial_choice,
            banner=banner,
        )
        self.push_screen(modal, self._on_refresh_panel_choice)  # type: ignore[attr-defined]

    def _on_refresh_panel_choice(self, choice: RefreshChoice | None) -> None:
        """Dispatch a panel choice, ignoring cancel."""
        if choice is None:
            return
        self._dispatch_refresh_choice(choice)

    def _dispatch_refresh_choice(self, choice: RefreshChoice) -> None:
        """Run the collaborator for one Refresh panel option."""
        if choice == "this_tab":
            RefreshPanelMixin._refresh_current_tab_surfaces(self)
            self.notify("Refreshed")  # type: ignore[attr-defined]
            return
        if choice == "full_history":
            RefreshPanelMixin.action_refresh_agents_full_history(self)
            return
        if choice == "usage":
            RefreshPanelMixin._refresh_usage_windows(self)
            return
        if choice == "everything":
            RefreshPanelMixin._refresh_everything(self)

    def _refresh_everything(self) -> None:
        """Force a sanity sweep, then full history and usage."""
        self._last_full_sanity_refresh = 0.0
        on_auto = getattr(self, "_on_auto_refresh", None)
        if callable(on_auto):
            on_auto()
        RefreshPanelMixin._refresh_agents_full_history(self)
        RefreshPanelMixin._refresh_usage_windows(self)
        self.notify("Refreshing everything")  # type: ignore[attr-defined]

    def _refresh_usage_windows(self) -> None:
        """Submit a provider usage refresh off the UI thread."""

        def task() -> None:
            receipt = submit_usage_refresh(None, explicit=True, origin="ace")
            call_from_thread = getattr(self, "call_from_thread", None)
            if callable(call_from_thread):
                call_from_thread(self._notify_usage_refresh_receipt, receipt)
                return
            self._notify_usage_refresh_receipt(receipt)

        self.run_worker(task, thread=True, exit_on_error=False)  # type: ignore[attr-defined]

    def _notify_usage_refresh_receipt(self, receipt: UsageRefreshReceipt) -> None:
        """Toast the outcome of a usage-window refresh."""
        disabled = any(item.reason == "config_disabled" for item in receipt.providers)
        if disabled and not receipt.started:
            self.notify(_USAGE_DISABLED_MESSAGE)  # type: ignore[attr-defined]
            return
        started = [item.provider for item in receipt.providers if item.operation_id]
        if started:
            self.notify(f"Refreshing usage: {', '.join(started)}")  # type: ignore[attr-defined]
            return
        self.notify(_USAGE_ALREADY_RUNNING)  # type: ignore[attr-defined]

    def _refresh_panel_rows(self) -> tuple[RefreshRow, ...]:
        """Build chooser rows from in-memory tab and freshness state."""
        tab_label = RefreshPanelMixin._refresh_tab_label(self)
        this_age = surface_refreshed_age(
            self, RefreshPanelMixin._this_tab_surface(self)
        )
        history_age = surface_refreshed_age(self, "agents_full_history")
        return (
            RefreshRow(
                choice="this_tab",
                key="r",
                aliases=("R", "enter", "1"),
                title="This tab",
                target=tab_label,
                subtitle=RefreshPanelMixin._this_tab_subtitle(self),
                chip=freshness_label(this_age),
                tone="primary",
            ),
            RefreshRow(
                choice="full_history",
                key="f",
                aliases=("2",),
                title="Full history",
                target="Agents",
                subtitle="Rescan every source artifact. Slower.",
                chip=freshness_label(history_age),
            ),
            RefreshRow(
                choice="usage",
                key="u",
                aliases=("3",),
                title="Usage windows",
                target="providers",
                subtitle="Re-probe provider subscription limits.",
                chip="",
            ),
            RefreshRow(
                choice="everything",
                key="a",
                aliases=("4",),
                title="Everything",
                target="",
                subtitle="Every surface, full history, and usage.",
                chip="heavier",
                tone="accent",
            ),
        )

    def _refresh_tab_label(self) -> str:
        """Return the current-tab label shown on the This-tab row."""
        tab = getattr(self, "current_tab", "agents")
        named = _TAB_LABELS.get(tab)
        if named is not None:
            return named
        pane = str(getattr(self, "current_artifacts_pane_key", "patches"))
        name = pane.rsplit(":", 1)[-1]
        return f"Artifacts › {name.replace('_', ' ').replace('-', ' ').title()}"

    def _this_tab_subtitle(self) -> str:
        """Return the This-tab subtitle for the current surface."""
        tab = getattr(self, "current_tab", "agents")
        if tab == "agents":
            return "Reload the visible inbox from the index."
        if tab == "axe":
            return "Reload the focused AXE panel and fleet."
        return "Reload the visible artifacts pane."

    def _this_tab_surface(self) -> str:
        """Return the freshness surface stamped by a This-tab refresh."""
        tab = getattr(self, "current_tab", "agents")
        if tab == "agents":
            return "agents"
        if tab == "axe":
            return "axe"
        if getattr(self, "current_artifacts_subtab", "patches") == "patches":
            return "patches"
        return "artifacts"

    def _auto_refresh_label(self) -> str | None:
        """Return the panel header line from the in-memory countdown."""
        interval = getattr(self, "refresh_interval", 0)
        if not interval:
            return None
        remaining = getattr(self, "_countdown_remaining", interval)
        try:
            remaining_s = max(0, int(remaining))
        except (TypeError, ValueError):
            remaining_s = int(interval)
        return f"auto-refresh every {int(interval)}s · next in {remaining_s}s"
