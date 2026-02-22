"""Axe control mixin for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sase.axe.state import (
    AxeMetrics,
    AxeStatus,
    clear_lumberjack_output_log,
    clear_output_log,
)

from ..bgcmd import BackgroundCommandInfo, clear_slot_output
from .axe_bgcmd import AxeBgCmdMixin
from .axe_display import AxeDisplayMixin, get_axe_process_module

if TYPE_CHECKING:
    from ...changespec import ChangeSpec

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
    _leader_mode_active: bool
    _bang_mode_active: bool

    # Background command state
    _axe_current_view: AxeViewType
    _bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]

    # Lumberjack cycling state
    _axe_lumberjack_names: list[str]
    _axe_lumberjack_idx: int | None

    def action_toggle_axe(self) -> None:
        """Toggle the axe daemon on or off (AXE tab only).

        On AXE tab:
          - View 0 (axe): Toggle axe daemon
          - View 1-9 (bgcmd): Show confirm dialog to kill that bgcmd

        On other tabs: no-op (use !x bang mode instead).
        """
        if self.current_tab != "axe":
            return

        # On AXE tab, behavior depends on current view
        if self._axe_current_view == "axe":
            # Toggle axe daemon
            if self.axe_running:
                self._stop_axe()
            else:
                self._start_axe()
        else:
            # Current view is a bgcmd slot - kill or clear
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
            # On AXE tab, behavior depends on current view
            if self._axe_current_view == "axe":
                # Toggle axe daemon
                if self.axe_running:
                    self._stop_axe()
                else:
                    self._start_axe()
            else:
                # Current view is a bgcmd slot - kill or clear
                slot = self._axe_current_view
                self._confirm_kill_bgcmd(slot)
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

        if key == "x":
            # !x → toggle axe / select process (global)
            self._toggle_axe_global()
            return True

        if key == "exclamation_mark":
            # !! → start background command
            self.action_start_bgcmd()
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
        self.exit()  # type: ignore[attr-defined]

    def action_clear_axe_output(self) -> None:
        """Clear the output log for the current view."""
        if self.current_tab != "axe":
            return

        if self._axe_current_view == "axe":
            if self._axe_lumberjack_idx is not None and self._axe_lumberjack_names:
                # Clear lumberjack-specific output
                lj_name = self._axe_lumberjack_names[self._axe_lumberjack_idx]
                clear_lumberjack_output_log(lj_name)
            else:
                # Clear main axe output
                clear_output_log()
                self._axe_output = ""
        else:
            # Clear bgcmd output
            slot = self._axe_current_view
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

    def _next_lumberjack(self) -> None:
        """Cycle to the next lumberjack output view.

        Wraps from last lumberjack back to first.
        Does nothing if no lumberjacks are configured.
        """
        if not self._axe_lumberjack_names:
            return
        if self._axe_lumberjack_idx is None:
            self._axe_lumberjack_idx = 0
        else:
            next_idx = self._axe_lumberjack_idx + 1
            if next_idx >= len(self._axe_lumberjack_names):
                self._axe_lumberjack_idx = 0
            else:
                self._axe_lumberjack_idx = next_idx
        self._refresh_axe_display()

    def _prev_lumberjack(self) -> None:
        """Cycle to the previous lumberjack output view.

        Wraps from first lumberjack back to last.
        Does nothing if no lumberjacks are configured.
        """
        if not self._axe_lumberjack_names:
            return
        if self._axe_lumberjack_idx is None:
            self._axe_lumberjack_idx = len(self._axe_lumberjack_names) - 1
        else:
            prev_idx = self._axe_lumberjack_idx - 1
            if prev_idx < 0:
                self._axe_lumberjack_idx = len(self._axe_lumberjack_names) - 1
            else:
                self._axe_lumberjack_idx = prev_idx
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
        if self.current_tab != "axe":
            return
        from ..modals import RunnersModal

        self.push_screen(RunnersModal())  # type: ignore[attr-defined]
