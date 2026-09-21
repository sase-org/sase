"""Axe control mixin for sase's TUI app."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from textual.worker import Worker, WorkerState

from sase.axe.state import clear_lumberjack_output_log

from ..bgcmd import BackgroundCommandInfo, clear_slot_output
from ..exit_action import AceExitAction
from ..tab_order import SERVICES_TAB
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
TabName = Literal["artifacts", "agents", "services"]

# Type alias for axe view: "axe" for daemon view, int for bgcmd slot (1-9)
AxeViewType = Literal["axe"] | int
AxeWorkerOperation = Literal["start", "stop", "restart", "enable", "disable"]

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
        if self.current_tab != SERVICES_TAB:
            return

        self.action_clear_axe_output()

    def action_toggle_axe_description(self) -> None:
        """Collapse or expand the selected config description for this session."""
        if self.current_tab != SERVICES_TAB:
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
            self._stop_service_host()
        else:
            self._start_service_host()

    def _toggle_or_kill_axe_view(self) -> None:
        """Toggle a selected service proc, or kill bgcmd based on AXE view.

        Bare ``x`` is contextual: a selected service-proc row toggles that
        proc. Nested Scheduler rows, empty selection, and host chrome are
        no-ops; ``!x`` toggles the host instead.
        """
        if self._axe_current_view == "axe":
            service_name = getattr(self, "_axe_service_selection", None)
            if service_name is not None:
                self._toggle_selected_service_proc(service_name)
            return
        slot = self._axe_current_view
        self._confirm_kill_bgcmd(slot)

    def _toggle_axe_global(self) -> None:
        """Toggle axe or select process (works on all tabs, triggered by !x).

        When on AXE / Services tab:
          - View ``"axe"``: always start/stop the service host (or legacy
            axe daemon), even if a proc or nested Scheduler row is selected
          - View 1-9 (bgcmd): Show confirm dialog to kill that bgcmd

        When on other tabs:
          - If axe not running and no bgcmd running: Start axe
          - If only axe running: Stop axe
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
                self._start_service_host()
            elif self.axe_running and not bgcmd_active:
                # Only the service host running - stop it
                self._stop_service_host()
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

        toggle_enablement_key = bang_keys.get("toggle_service_enablement")
        if toggle_enablement_key == key:
            self._toggle_selected_service_enablement()
            self._refresh_current_tab()  # type: ignore[attr-defined]
            return True

        if key == bang_keys["run_cmd"]:
            # !! → start background command
            self.action_start_bgcmd()
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
        """Stop the Scheduler, then quit."""
        stop_watchdog = getattr(self, "_stop_tui_stall_watchdog", None)
        if callable(stop_watchdog):
            stop_watchdog()

        try:
            from sase.service.actions import stop_service_proc

            # Stops Scheduler only; the service host is never stopped here.
            await asyncio.to_thread(
                stop_service_proc,
                "scheduler",
                actor="tui",
                reason="ace quit",
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

        request_exit = getattr(self, "_request_controlled_exit", None)
        if callable(request_exit):
            request_exit()
        else:
            self._do_quit()  # type: ignore[attr-defined]

    def action_clear_axe_output(self) -> None:
        """Clear the output log for the current view."""
        from ..widgets.bgcmd_list import BgCmdItem, ChopItem, LumberjackItem

        if self.current_tab != SERVICES_TAB:
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
                    "Job run history is immutable from the TUI",
                    severity="warning",
                )
            case BgCmdItem(slot=slot):
                info = dict(self._bgcmd_slots).get(slot)
                if info is None:
                    return
                if getattr(self, "_axe_bgcmd_details", None):
                    snap = self._axe_bgcmd_details.get(slot)
                    if snap is not None:
                        snap.output_tail = ""
                self.run_worker(  # type: ignore[attr-defined]
                    lambda: clear_slot_output(slot, info),
                    thread=True,
                    exclusive=False,
                    exit_on_error=False,
                    group="bgcmd-clear-output",
                )
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
                if self.current_tab == SERVICES_TAB:
                    self.current_idx = idx
                self._axe_last_idx = idx
                self._axe_last_item_key = key
        self._refresh_axe_display()

    def _selected_service_proc(self, name: str | None = None) -> Any | None:
        """Return the selected service proc status from the cached snapshot."""
        service_name = (
            name if name is not None else getattr(self, "_axe_service_selection", None)
        )
        snapshot = getattr(self, "_service_status", None)
        if service_name is None or snapshot is None:
            return None
        return next(
            (proc for proc in snapshot.procs if proc.name == service_name), None
        )

    def _toggle_selected_service_proc(self, name: str) -> None:
        """Start or stop the selected service proc."""
        proc = self._selected_service_proc(name)
        if proc is None:
            self.notify("Service proc status unavailable", severity="warning")  # type: ignore[attr-defined]
            return
        if not proc.available:
            self.notify("Service proc is unavailable", severity="warning")  # type: ignore[attr-defined]
            return
        if not proc.enablement.enabled:
            self.notify("Service proc is disabled", severity="warning")  # type: ignore[attr-defined]
            return
        action: AxeWorkerOperation = "stop" if proc.state == "running" else "start"
        self._run_service_proc_action(name, action)

    def _restart_selected_service_proc(self) -> None:
        """Restart the selected service proc."""
        name = getattr(self, "_axe_service_selection", None)
        proc = self._selected_service_proc(name)
        if name is None or proc is None:
            self.notify("No service proc selected", severity="warning")  # type: ignore[attr-defined]
            return
        if not proc.available:
            self.notify("Service proc is unavailable", severity="warning")  # type: ignore[attr-defined]
            return
        if not proc.enablement.enabled:
            self.notify("Service proc is disabled", severity="warning")  # type: ignore[attr-defined]
            return
        self._run_service_proc_action(name, "restart")

    def _toggle_selected_service_enablement(self) -> None:
        """Enable or disable the selected service proc for this machine."""
        name = getattr(self, "_axe_service_selection", None)
        proc = self._selected_service_proc(name)
        if name is None or proc is None:
            self.notify("Select a service proc first", severity="warning")  # type: ignore[attr-defined]
            return
        action: AxeWorkerOperation = "disable" if proc.enablement.enabled else "enable"
        self._run_service_proc_action(name, action)

    def _run_service_proc_action(self, name: str, action: AxeWorkerOperation) -> None:
        """Run a service-proc action in the shared AXE worker slot."""
        if self._axe_worker is not None:
            return
        if action == "start":
            self._set_axe_starting(True)
        elif action == "stop":
            self._set_axe_stopping(True)
        elif action == "restart":
            self._set_axe_restarting(True)
        self._axe_worker_operation = action

        def _do_action() -> tuple[bool, str]:
            from sase.service.actions import (
                ServiceProcActionError,
                disable_service_proc,
                enable_service_proc,
                restart_service_proc,
                start_service_proc,
                stop_service_proc,
            )

            try:
                if action == "start":
                    outcome = start_service_proc(name, actor="tui")
                elif action == "stop":
                    outcome = stop_service_proc(name, actor="tui", reason="tui")
                elif action == "restart":
                    outcome = restart_service_proc(
                        name,
                        actor="tui",
                        reason="tui",
                    )
                elif action == "enable":
                    outcome = enable_service_proc(name, actor="tui")
                else:
                    outcome = disable_service_proc(name, actor="tui")
            except ServiceProcActionError as exc:
                return (False, str(exc))
            return (True, outcome.message)

        self._axe_worker = self.run_worker(_do_action, thread=True)  # type: ignore[attr-defined]

    def _start_service_host(self) -> None:
        """Start the service host in a background worker thread."""
        if self._axe_worker is not None:
            return
        self._set_axe_starting(True)
        self._axe_worker_operation = "start"

        def _do_start() -> tuple[bool, str]:
            from sase.service.control import start_service_host

            result = start_service_host()
            return (result.ok, result.message)

        self._axe_worker = self.run_worker(_do_start, thread=True)  # type: ignore[attr-defined]

    def _stop_service_host(self) -> None:
        """Stop the service host in a background worker thread."""
        if self._axe_worker is not None:
            return
        self._set_axe_stopping(True)
        self._axe_worker_operation = "stop"

        def _do_stop() -> tuple[bool, str]:
            from sase.service.control import stop_service_host

            result = stop_service_host()
            return (result.ok, result.message)

        self._axe_worker = self.run_worker(_do_stop, thread=True)  # type: ignore[attr-defined]

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
        from ..proc_observer import proc_projection_for

        rows = proc_projection_for(self).rows
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
            for t in rows
        ]

        self.push_screen(RunnersModal(background_procs=bg_procs), on_dismiss)  # type: ignore[attr-defined]
