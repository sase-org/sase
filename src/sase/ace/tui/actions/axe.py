"""Axe control mixin for the ace TUI app."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from textual.worker import Worker, WorkerState

from sase.axe.process import (
    restart_axe_daemon_result as _restart_axe_daemon_result,
    start_axe_daemon_result as _start_axe_daemon_result,
    stop_axe_daemon_result as _stop_axe_daemon_result,
)
from sase.axe.state import (
    AxeMetrics,
    AxeStatus,
    clear_lumberjack_output_log,
)

from ..bgcmd import BackgroundCommandInfo, clear_slot_output
from ..exit_action import AceExitAction
from .axe_bgcmd import AxeBgCmdMixin
from .axe_chop_run import AxeChopRunMixin
from .axe_config_actions import AxeConfigActionsMixin
from .axe_display import AxeDisplayMixin

if TYPE_CHECKING:
    from ...patch import Patch
    from ..keymaps import KeymapRegistry
    from ..modals import QuitOption
    from .axe_display._loaders import AxeItemKey
    from .axe_display._data import AxeStatusDegradation

# Type alias for tab names
TabName = Literal["artifacts", "agents", "axe"]

# Type alias for axe view: "axe" for daemon view, int for bgcmd slot (1-9)
AxeViewType = Literal["axe"] | int
AxeWorkerOperation = Literal["start", "stop", "restart"]

_POST_AXE_WORKER_STATUS_REPOLL_DELAYS = (0.25, 0.75, 1.5, 3.0)


class AxeMixin(AxeConfigActionsMixin, AxeBgCmdMixin, AxeChopRunMixin, AxeDisplayMixin):
    """Mixin providing axe daemon control and display methods."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    refresh_interval: int
    axe_running: bool
    axe_description_expanded: bool
    _countdown_remaining: int
    _axe_status: AxeStatus | None
    _axe_metrics: AxeMetrics | None
    _axe_output: str
    _axe_degraded_status: AxeStatusDegradation | None
    _axe_pinned_to_bottom: bool
    _axe_cmds_hidden: bool
    _leader_mode_active: bool
    _bang_mode_active: bool
    _keymap_registry: KeymapRegistry
    _axe_worker: Worker[Any] | None
    _axe_worker_operation: AxeWorkerOperation | None
    _axe_config_restart_saved_path: str | None

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

    def action_toggle_axe_description(self) -> None:
        """Collapse or expand the selected config description for this session."""
        if self.current_tab != "axe":
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
        """Open the quit / restart options panel."""
        from ..modals import QuitOptionsModal

        def _on_choice(choice: QuitOption | None) -> None:
            if choice is None:
                return
            if choice == "quit_stop_axe":
                self.run_worker(self._stop_axe_and_quit())  # type: ignore[attr-defined]
                return
            self._restart_tui(restart_axe=choice == "restart_tui_and_axe")

        self.push_screen(  # type: ignore[attr-defined]
            QuitOptionsModal(
                running_task_count=self._count_running_tasks(),  # type: ignore[attr-defined]
            ),
            callback=_on_choice,
        )

    async def _stop_axe_and_quit(self) -> None:
        """Stop axe with the robust daemon stop path, then quit."""
        stop_watchdog = getattr(self, "_stop_tui_stall_watchdog", None)
        if callable(stop_watchdog):
            stop_watchdog()

        try:
            self._kill_all_running_tasks()  # type: ignore[attr-defined]
        except Exception:
            pass

        try:
            await asyncio.to_thread(
                _stop_axe_daemon_result,
                timeout=5.0,
                kill_timeout=2.0,
                desired_state_source="ace quit",
            )
        except Exception:
            pass
        finally:
            begin_exit = getattr(self, "_begin_controlled_exit", None)
            if callable(begin_exit):
                await begin_exit()
            else:
                self._do_quit()  # type: ignore[attr-defined]

    def _restart_tui(self, *, restart_axe: bool) -> None:
        """Quit this TUI and ask the command handler to re-exec it."""
        self.exit_action = (
            AceExitAction.RESTART_TUI_AND_AXE
            if restart_axe
            else AceExitAction.RESTART_TUI
        )

        stop_watchdog = getattr(self, "_stop_tui_stall_watchdog", None)
        if callable(stop_watchdog):
            stop_watchdog()

        draft_stashed = False
        stash_before_restart = getattr(self, "_stash_prompt_bar_before_restart", None)
        if callable(stash_before_restart):
            try:
                draft_stashed = bool(stash_before_restart())
            except Exception:
                draft_stashed = False
        if draft_stashed:
            try:
                self.notify(  # type: ignore[attr-defined]
                    "Prompt draft stashed; press @ to restore after restart"
                )
            except Exception:
                pass

        try:
            self._kill_all_running_tasks()  # type: ignore[attr-defined]
        except Exception:
            pass
        finally:
            request_exit = getattr(self, "_request_controlled_exit", None)
            if callable(request_exit):
                request_exit()
            else:
                self._do_quit()  # type: ignore[attr-defined]

    def action_clear_axe_output(self) -> None:
        """Clear the output log for the current view."""
        from ..widgets.bgcmd_list import BgCmdItem, ChopItem, LumberjackItem

        if self.current_tab != "axe":
            return

        # Derive what to clear from the selected item. Chop run history is
        # immutable from the TUI (the safer default): the affordance is
        # a no-op on chop rows and surfaces a warning instead of silently
        # mutating the parent lumberjack log behind the user's back.
        axe_items = self._axe_items  # type: ignore[attr-defined]
        if not axe_items or self.current_idx >= len(axe_items):
            return

        item = axe_items[self.current_idx]
        match item:
            case LumberjackItem(name=name):
                clear_lumberjack_output_log(name)
                self._refresh_axe_display()
                self.notify("Output cleared")  # type: ignore[attr-defined]
            case ChopItem():
                self.notify(  # type: ignore[attr-defined]
                    "Chop run history is immutable from the TUI",
                    severity="warning",
                )
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
        # The synthetic "axe" view no longer has a selectable row in the
        # sidebar; only bgcmd slots have a stable identity to home to.
        if view != "axe":
            key: AxeItemKey = ("bgcmd", view)
            idx = find_axe_item_idx(self._axe_items, key)  # type: ignore[attr-defined]
            if idx is not None:
                if self.current_tab == "axe":
                    self.current_idx = idx
                self._axe_last_idx = idx
                self._axe_last_item_key = key
        self._refresh_axe_display()

    def _start_axe(self, *, source: str = "ace start") -> None:
        """Start the axe daemon in a background worker thread."""
        if self._axe_worker is not None:
            return  # Start/stop already in progress
        self._set_axe_starting(True)
        self._axe_worker_operation = "start"

        def _do_start() -> tuple[bool, str]:
            result = _start_axe_daemon_result(desired_state_source=source)
            if result.pid is not None:
                return (True, f"Axe running (pid {result.pid})")
            return (False, result.message or "Failed to start axe")

        self._axe_worker = self.run_worker(_do_start, thread=True)  # type: ignore[attr-defined]

    def _stop_axe(self, *, source: str = "ace stop") -> None:
        """Stop the axe daemon in a background worker thread."""
        if self._axe_worker is not None:
            return  # Start/stop already in progress
        self._set_axe_stopping(True)
        self._axe_worker_operation = "stop"

        def _do_stop() -> tuple[bool, str]:
            result = _stop_axe_daemon_result(desired_state_source=source)
            if result.terminated_anything:
                return (True, result.summary())
            return (False, result.summary())

        self._axe_worker = self.run_worker(_do_stop, thread=True)  # type: ignore[attr-defined]

    def _restart_axe_daemon(self, *, source: str = "ace restart") -> None:
        """Restart axe daemon: stop then start in a background worker."""
        if self._axe_worker is not None:
            return
        self._set_axe_restarting(True)
        self._axe_worker_operation = "restart"

        def _do_restart() -> tuple[bool, str]:
            result = _restart_axe_daemon_result(desired_state_source=source)
            if result.pid is not None:
                return (True, f"Axe restarted (pid {result.pid})")
            return (False, result.message or "Failed to restart axe")

        self._axe_worker = self.run_worker(_do_restart, thread=True)  # type: ignore[attr-defined]

    def _on_axe_worker_done(self, worker: Worker[Any], state: WorkerState) -> None:
        """Handle axe start/stop worker completion."""
        operation = self._axe_worker_operation
        saved_path = getattr(self, "_axe_config_restart_saved_path", None)
        self._axe_config_restart_saved_path = None
        self._axe_worker = None
        self._axe_worker_operation = None
        worker_succeeded = False

        if state == WorkerState.SUCCESS and worker.result is not None:
            success, message = worker.result
            worker_succeeded = success
            if not success:
                if saved_path:
                    message = (
                        f"Config saved to {saved_path}, but AXE restart failed: "
                        f"{message}"
                    )
                self.notify(message, severity="error")  # type: ignore[attr-defined]
            elif saved_path:
                self.notify(f"Config saved to {saved_path}; AXE restarted")  # type: ignore[attr-defined]
        elif state == WorkerState.ERROR:
            error_msg = str(worker.error) if worker.error else "Unknown error"
            message = f"Axe operation failed: {error_msg}"
            if saved_path:
                message = (
                    f"Config saved to {saved_path}, but AXE restart failed: {error_msg}"
                )
            self.notify(message, severity="error")  # type: ignore[attr-defined]

        if saved_path:
            self._schedule_axe_async_refresh()
        else:
            self._load_axe_status()
        self._clear_axe_transition_flags()
        if (
            worker_succeeded
            and operation in ("start", "restart")
            and not self.axe_running
        ):
            self._schedule_post_axe_worker_status_repolls()

    def _clear_axe_transition_flags(self) -> None:
        """Clear transient axe operation indicators after a worker completes."""
        self._set_axe_starting(False)
        self._set_axe_restarting(False)
        self._set_axe_stopping(False)

    def _schedule_post_axe_worker_status_repolls(self) -> None:
        """Schedule bounded follow-up status reads after a lagging start."""
        for delay in _POST_AXE_WORKER_STATUS_REPOLL_DELAYS:
            self.set_timer(delay, self._schedule_axe_async_refresh)  # type: ignore[attr-defined]

    def action_show_runners(self) -> None:
        """Show the runners modal with all current runners."""
        from ..modals import RunnersModal
        from ..modals.runners_modal import BackgroundProcEntry, RunnerJumpTarget

        def on_dismiss(result: RunnerJumpTarget | None) -> None:
            if result is None:
                return

            if result.jump_tab == "artifacts":
                from .agents._notification_actions import navigate_to_patch_tab

                navigate_to_patch_tab(self, result.cl_name, result.project_file)
            else:  # agents
                from .agents._notification_actions import navigate_to_agent_tab

                navigate_to_agent_tab(self, result.cl_name, result.pid)

        # Collect background procs for the modal
        bg_procs = [
            BackgroundProcEntry(
                proc_type=t.proc_type,
                cl_name=t.cl_name,
                project_file=t.project_file,
                status=t.status,
                message=t.message,
                started_at=t.started_at,
                finished_at=t.finished_at,
            )
            for t in self._proc_queue.get_all()  # type: ignore[attr-defined]
        ]

        self.push_screen(RunnersModal(background_procs=bg_procs), on_dismiss)  # type: ignore[attr-defined]
