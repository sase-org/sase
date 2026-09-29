"""Axe toggle and bang-mode actions for sase's TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ..tab_order import SERVICES_TAB

if TYPE_CHECKING:
    from ...patch import Patch
    from ..keymaps import KeymapRegistry

# Type alias for tab names
TabName = Literal["artifacts", "agents", "services"]

# Type alias for axe view: "axe" for daemon view, int for bgcmd slot (1-9)
AxeViewType = Literal["axe"] | int


class AxeToggleMixin:
    """Mixin providing axe toggle and bang-mode key handling."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    axe_running: bool
    axe_description_expanded: bool
    _bang_mode_active: bool
    _keymap_registry: KeymapRegistry
    _axe_current_view: AxeViewType
    _bgcmd_slots: list[Any]

    def action_toggle_axe(self) -> None:
        """Dispatch the tab-local ``X`` action."""
        if self.current_tab == "agents":
            self.action_open_agent_cleanup_panel()  # type: ignore[attr-defined]
            return
        if self.current_tab != SERVICES_TAB:
            return

        self.action_clear_axe_output()  # type: ignore[attr-defined]

    def _axe_description_row_selected(self) -> bool:
        """Return whether the selected row owns a description panel."""
        from ..widgets.bgcmd_list import ChopItem, LumberjackItem, ServiceProcItem

        axe_items = getattr(self, "_axe_items", None)
        if not axe_items:
            return False
        idx = getattr(self, "current_idx", 0)
        if idx < 0 or idx >= len(axe_items):
            return False
        return isinstance(axe_items[idx], (ServiceProcItem, LumberjackItem, ChopItem))

    def action_toggle_axe_description(self) -> None:
        """Collapse or expand the selected config description for this session."""
        if self.current_tab != SERVICES_TAB:
            return
        if not self._axe_description_row_selected():
            return

        self.axe_description_expanded = not self.axe_description_expanded
        from ..widgets import AxeDashboard

        try:
            dashboard = self.query_one("#axe-dashboard", AxeDashboard)  # type: ignore[attr-defined]
            dashboard.refresh_description_banner(self.axe_description_expanded)
        except Exception:
            pass

        # This is a cache-only repaint; it updates the conditional footer label
        # without loading configuration or touching any AXE data source.
        refresh = getattr(self, "_refresh_axe_display", None)
        if callable(refresh):
            refresh()

    def _toggle_host_or_axe_daemon(self) -> None:
        """Start or stop the service host."""
        if self.axe_running:
            self._stop_service_host()  # type: ignore[attr-defined]
        else:
            self._start_service_host()  # type: ignore[attr-defined]

    def _toggle_or_kill_axe_view(self) -> None:
        """Toggle a selected service proc, or kill bgcmd based on AXE view.

        Bare ``x`` is contextual: a selected service-proc row toggles that
        proc. Nested Scheduler rows, empty selection, and host chrome are
        no-ops; ``!x`` toggles the host instead.
        """
        if self._axe_current_view == "axe":
            service_name = getattr(self, "_axe_service_selection", None)
            if service_name is not None:
                self._toggle_selected_service_proc(service_name)  # type: ignore[attr-defined]
            return
        slot = self._axe_current_view
        self._confirm_kill_bgcmd(slot)  # type: ignore[attr-defined]

    def _toggle_axe_global(self) -> None:
        """Toggle the service host or select process (works on all tabs, triggered by !x).

        When on the Services tab:
          - View ``"axe"``: always start/stop the service host, even if a
            proc or nested Scheduler row is selected
          - View 1-9 (bgcmd): Show confirm dialog to kill that bgcmd

        When on other tabs:
          - If service host not running and no bgcmd running: Start host
          - If only service host running: Stop host
          - If only bgcmd running: Show selector
          - If both running: Show selector
        """
        if self.current_tab == SERVICES_TAB:
            if self._axe_current_view == "axe":
                self._toggle_host_or_axe_daemon()
                return
            self._toggle_or_kill_axe_view()
        else:
            # On other tabs - handle based on what's running
            bgcmd_active = len(self._bgcmd_slots) > 0

            if not self.axe_running and not bgcmd_active:
                # Nothing running - start the service host
                self._start_service_host()  # type: ignore[attr-defined]
            elif self.axe_running and not bgcmd_active:
                # Only the service host running - stop it
                self._stop_service_host()  # type: ignore[attr-defined]
            else:
                # Either only bgcmd or both running - show selector
                self._show_process_selector()  # type: ignore[attr-defined]

    def action_start_bang_mode(self) -> None:
        """Enter bang mode prefix (! key on all tabs)."""
        self._bang_mode_active = True
        self._update_bang_footer()

    def _handle_bang_key(self, key: str) -> bool:
        """Handle a key press in bang mode.

        Args:
            key: The key that was pressed.

        Returns:
            True if the key was handled, False otherwise.
        """
        # Always exit bang mode
        self._bang_mode_active = False

        if key == "escape":
            # Cancel silently and restore footer
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        bang_keys = self._keymap_registry.bang_mode.keys

        if key == bang_keys["toggle_axe"]:
            # !x → toggle axe / select process (global)
            self._toggle_axe_global()
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        toggle_enablement_key = bang_keys.get("toggle_service_enablement")
        if toggle_enablement_key == key:
            self._toggle_selected_service_enablement()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == bang_keys["run_cmd"]:
            # !! → start background command
            self.action_start_bgcmd()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        mark_pr_origin_key = bang_keys.get("mark_pr_origin")
        if mark_pr_origin_key == key:
            # !o → mark PR origin (moved off app-level `o` so grouping can use it)
            self.action_mark_pr_origin()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        start_rewind_key = bang_keys.get("start_rewind")
        if start_rewind_key == key:
            # !R → rewind Patch / revive agent (moved off app-level `R` so
            # unified pane refresh can use it)
            self.action_start_rewind()  # type: ignore[attr-defined]
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        # Unknown key - just exit mode and restore footer
        self._refresh_current_tab()  # type: ignore[attr-defined]
        return True

    def _update_bang_footer(self) -> None:
        """Update the footer to show bang mode bindings."""
        from ..widgets import KeybindingFooter

        try:
            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.update_bang_bindings()
        except Exception:
            pass
