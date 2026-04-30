"""Axe control mixin for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from textual.worker import Worker, WorkerState

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
    from ..keymaps import KeymapRegistry
    from .axe_display._loaders import AxeItemKey

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
    _axe_worker: Worker[Any] | None

    # Background command state
    _axe_current_view: AxeViewType
    _bgcmd_slots: list[tuple[int, BackgroundCommandInfo]]
    _axe_last_idx: int
    _axe_last_item_key: AxeItemKey | None

    # Lumberjack cycling state
    _axe_lumberjack_names: list[str]
    _axe_lumberjack_idx: int | None

    def action_toggle_axe(self) -> None:
        """Dispatch the tab-local ``X`` action."""
        if self.current_tab == "agents":
            self.action_open_agent_cleanup_panel()  # type: ignore[attr-defined]
            return
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
            # Send SIGTERM directly without waiting — the daemon is detached
            # and handles its own graceful shutdown.
            import os
            import signal

            proc = get_axe_process_module()
            pid = proc.get_axe_pid()
            if pid is not None:
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
        self._kill_all_running_tasks()  # type: ignore[attr-defined]
        self._do_quit()  # type: ignore[attr-defined]

    def action_clear_axe_output(self) -> None:
        """Clear the output log for the current view."""
        from ..widgets.bgcmd_list import AxeParentItem, BgCmdItem, LumberjackItem

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
            case LumberjackItem(name=name):
                clear_lumberjack_output_log(name)
            case BgCmdItem(slot=slot):
                clear_slot_output(slot)

        self._refresh_axe_display()
        self.notify("Output cleared")  # type: ignore[attr-defined]

    def _switch_to_axe_view(self, view: AxeViewType) -> None:
        """Switch to a different axe view.

        Args:
            view: The view to switch to ("axe" or slot number).
        """
        from .axe_display._loaders import find_axe_item_idx

        self._axe_current_view = view
        key: AxeItemKey = ("axe", None) if view == "axe" else ("bgcmd", view)
        idx = find_axe_item_idx(self._axe_items, key)  # type: ignore[attr-defined]
        if idx is not None:
            if self.current_tab == "axe":
                self.current_idx = idx
            self._axe_last_idx = idx
            self._axe_last_item_key = key
        self._refresh_axe_display()

    def _start_axe(self) -> None:
        """Start the axe daemon in a background worker thread."""
        if self._axe_worker is not None:
            return  # Start/stop already in progress
        self._set_axe_starting(True)

        def _do_start() -> tuple[bool, str]:
            proc = get_axe_process_module()
            pid = proc.start_axe_daemon()
            if pid is not None:
                return (True, f"Axe started (pid {pid})")
            return (False, "Failed to start axe")

        self._axe_worker = self.run_worker(_do_start, thread=True)  # type: ignore[attr-defined]

    def _stop_axe(self) -> None:
        """Stop the axe daemon in a background worker thread."""
        if self._axe_worker is not None:
            return  # Start/stop already in progress
        self._set_axe_stopping(True)

        def _do_stop() -> tuple[bool, str]:
            proc = get_axe_process_module()
            stopped = proc.stop_axe_daemon()
            if stopped:
                return (True, "Axe stopped")
            return (False, "Axe was not running")

        self._axe_worker = self.run_worker(_do_stop, thread=True)  # type: ignore[attr-defined]

    def _restart_axe_daemon(self) -> None:
        """Restart axe daemon: stop then start in a background worker."""
        if self._axe_worker is not None:
            return
        self._set_axe_restarting(True)

        def _do_restart() -> tuple[bool, str]:
            proc = get_axe_process_module()
            stopped = proc.stop_axe_daemon()
            if not stopped:
                return (False, "Axe was not running")
            pid = proc.start_axe_daemon()
            if pid is not None:
                return (True, f"Axe restarted (pid {pid})")
            return (False, "Failed to restart axe")

        self._axe_worker = self.run_worker(_do_restart, thread=True)  # type: ignore[attr-defined]

    def _on_axe_worker_done(self, worker: Worker[Any], state: WorkerState) -> None:
        """Handle axe start/stop worker completion."""
        self._axe_worker = None

        if state == WorkerState.SUCCESS and worker.result is not None:
            success, message = worker.result
            if not success:
                self.notify(message, severity="error")  # type: ignore[attr-defined]
        elif state == WorkerState.ERROR:
            error_msg = str(worker.error) if worker.error else "Unknown error"
            self.notify(f"Axe operation failed: {error_msg}", severity="error")  # type: ignore[attr-defined]

        self._load_axe_status()

    def action_show_runners(self) -> None:
        """Show the runners modal with all current runners."""
        from ..modals import RunnersModal
        from ..modals.runners_modal import BackgroundTaskEntry, RunnerJumpTarget

        def on_dismiss(result: RunnerJumpTarget | None) -> None:
            if result is None:
                return

            if result.jump_tab == "changespecs":
                from .agents._notification_actions import navigate_to_changespec_tab

                navigate_to_changespec_tab(self, result.cl_name, result.project_file)
            else:  # agents
                from .agents._notification_actions import navigate_to_agent_tab

                navigate_to_agent_tab(self, result.cl_name, result.pid)

        # Collect background tasks for the modal
        bg_tasks = [
            BackgroundTaskEntry(
                task_type=t.task_type,
                cl_name=t.cl_name,
                project_file=t.project_file,
                status=t.status,
                message=t.message,
                started_at=t.started_at,
                finished_at=t.finished_at,
            )
            for t in self._task_queue.get_all()  # type: ignore[attr-defined]
        ]

        self.push_screen(RunnersModal(background_tasks=bg_tasks), on_dismiss)  # type: ignore[attr-defined]
