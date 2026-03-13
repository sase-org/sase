"""Axe control mixin for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sase.axe.state import (
    AxeMetrics,
    AxeStatus,
    clear_jack_output_log,
    clear_output_log,
)

from ..bgcmd import BackgroundCommandInfo, clear_slot_output
from .axe_bgcmd import AxeBgCmdMixin
from .axe_display import AxeDisplayMixin, get_axe_process_module

if TYPE_CHECKING:
    from ...changespec import ChangeSpec
    from ..keymaps import KeymapRegistry

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

# Type alias for axe view: "axe" for daemon view, int for bgcmd slot (1-9)
AxeViewType = Literal["axe"] | int


class AxeMixin(AxeBgCmdMixin, AxeDisplayMixin):
    """Mixin providing axe daemon control and display methods."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: TabName
    refresh_interval: int
    axe_running: bool
    _countdown_remaining: int
    _axe_status: AxeStatus | None
    _axe_metrics: AxeMetrics | None
    _axe_output: str
    _axe_pinned_to_bottom: bool
    _axe_cmds_hidden: bool
    _leader_mode_active: bool
    _bang_mode_active: bool
    _keymap_registry: KeymapRegistry

    # Background command state
    _axe_current_view: AxeViewType
    _bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]

    # Jack cycling state
    _axe_jack_names: list[str]
    _axe_jack_idx: int | None

    def action_toggle_axe(self) -> None:
        """Clear AXE output (X key on AXE tab).

        On other tabs: no-op.
        """
        if self.current_tab != "axe":
            return

        self.action_clear_axe_output()

    def _toggle_or_kill_axe_view(self) -> None:
        """Toggle axe daemon or kill bgcmd based on current AXE view.

        - View "axe": Toggle axe daemon on/off
        - View 1-9 (bgcmd): Show confirm dialog to kill that bgcmd
        """
        if self._axe_current_view == "axe":
            if self.axe_running:
                self._stop_axe()
            else:
                self._start_axe()
        else:
            slot = self._axe_current_view
            self._confirm_kill_bgcmd(slot)

    def _toggle_axe_global(self) -> None:
        """Toggle axe or select process (works on all tabs, triggered by !x).

        When on AXE tab:
          - View 0 (axe): Toggle axe daemon
          - View 1-9 (bgcmd): Show confirm dialog to kill that bgcmd

        When on other tabs:
          - If axe not running and no bgcmd running: Start axe
          - If only axe running: Stop axe
          - If only bgcmd running: Show selector
          - If both running: Show selector
        """
        if self.current_tab == "axe":
            self._toggle_or_kill_axe_view()
        else:
            # On other tabs - handle based on what's running
            bgcmd_active = len(self._bgcmd_slots) > 0

            if not self.axe_running and not bgcmd_active:
                # Nothing running - start axe
                self._start_axe()
            elif self.axe_running and not bgcmd_active:
                # Only axe running - stop it
                self._stop_axe()
            else:
                # Either only bgcmd or both running - show selector
                self._show_process_selector()

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

        if key == bang_keys["run_cmd"]:
            # !! → start background command
            self.action_start_bgcmd()
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

    def action_stop_axe_and_quit(self) -> None:
        """Stop the axe daemon and quit the application."""
        if self.axe_running:
            self._stop_axe()
        self._save_current_selection()  # type: ignore[attr-defined]
        from sase.ace.tui_activity import (
            remove_idle_state,
            remove_tui_pid,
            write_activity_timestamp,
        )

        import time

        write_activity_timestamp(time.time())
        remove_idle_state()
        remove_tui_pid()
        self.exit()  # type: ignore[attr-defined]

    def action_clear_axe_output(self) -> None:
        """Clear the output log for the current view."""
        from ..widgets.bgcmd_list import AxeParentItem, BgCmdItem, JackItem

        if self.current_tab != "axe":
            return

        # Derive what to clear from the selected item
        axe_items = self._axe_items  # type: ignore[attr-defined]
        if not axe_items or self.current_idx >= len(axe_items):
            return

        item = axe_items[self.current_idx]
        match item:
            case AxeParentItem():
                clear_output_log()
                self._axe_output = ""
            case JackItem(name=name):
                clear_jack_output_log(name)
            case BgCmdItem(slot=slot):
                clear_slot_output(slot)

        self._refresh_axe_display()
        self.notify("Output cleared")  # type: ignore[attr-defined]

    def _switch_to_axe_view(self, view: AxeViewType) -> None:
        """Switch to a different axe view.

        Args:
            view: The view to switch to ("axe" or slot number).
        """
        self._axe_current_view = view
        self._refresh_axe_display()

    def _start_axe(self) -> None:
        """Start the axe daemon."""
        try:
            self._set_axe_starting(True)
            proc = get_axe_process_module()
            proc.start_axe_daemon()
            self._load_axe_status()
        except Exception as e:
            self._set_axe_starting(False)
            self.notify(f"Failed to start axe: {e}", severity="error")  # type: ignore[attr-defined]

    def _stop_axe(self) -> None:
        """Stop the axe daemon."""
        try:
            self._set_axe_stopping(True)
            proc = get_axe_process_module()
            proc.stop_axe_daemon()
            self._load_axe_status()
        except Exception as e:
            self._set_axe_stopping(False)
            self.notify(f"Failed to stop axe: {e}", severity="error")  # type: ignore[attr-defined]

    def action_show_runners(self) -> None:
        """Show the runners modal with all current runners."""
        from ..modals import RunnersModal

        self.push_screen(RunnersModal())  # type: ignore[attr-defined]
