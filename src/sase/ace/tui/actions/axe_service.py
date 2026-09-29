"""Axe service-proc and host lifecycle actions for sase's TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from textual.worker import Worker, WorkerState

from ..tab_order import SERVICES_TAB

if TYPE_CHECKING:
    from ...patch import Patch
    from .axe_display._data import AxeStatusDegradation
    from .axe_display._loaders import AxeItemKey

# Type alias for tab names
TabName = Literal["artifacts", "agents", "services"]

# Type alias for axe view: "axe" for daemon view, int for bgcmd slot (1-9)
AxeViewType = Literal["axe"] | int
AxeWorkerOperation = Literal["start", "stop", "restart", "enable", "disable"]

_POST_AXE_WORKER_STATUS_REPOLL_DELAYS = (0.25, 0.75, 1.5, 3.0)


class AxeServiceMixin:
    """Mixin providing axe service-proc and host lifecycle actions."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    axe_running: bool
    _axe_degraded_status: AxeStatusDegradation | None
    _axe_worker: Worker[Any] | None
    _axe_worker_operation: AxeWorkerOperation | None
    _axe_config_restart_saved_path: str | None
    _axe_current_view: AxeViewType
    _axe_last_idx: int
    _axe_last_item_key: AxeItemKey | None

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
        self._refresh_axe_display()  # type: ignore[attr-defined]

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
            self._set_axe_starting(True)  # type: ignore[attr-defined]
        elif action == "stop":
            self._set_axe_stopping(True)  # type: ignore[attr-defined]
        elif action == "restart":
            self._set_axe_restarting(True)  # type: ignore[attr-defined]
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
        self._set_axe_starting(True)  # type: ignore[attr-defined]
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
        self._set_axe_stopping(True)  # type: ignore[attr-defined]
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
                        f"Config saved to {saved_path}, but scheduler restart failed: "
                        f"{message}"
                    )
                self.notify(message, severity="error")  # type: ignore[attr-defined]
            elif saved_path:
                self.notify(f"Config saved to {saved_path}; scheduler restarted")  # type: ignore[attr-defined]
        elif state == WorkerState.ERROR:
            error_msg = str(worker.error) if worker.error else "Unknown error"
            message = f"Service operation failed: {error_msg}"
            if saved_path:
                message = f"Config saved to {saved_path}, but scheduler restart failed: {error_msg}"
            self.notify(message, severity="error")  # type: ignore[attr-defined]

        if saved_path:
            self._schedule_axe_async_refresh()  # type: ignore[attr-defined]
        else:
            self._load_axe_status()  # type: ignore[attr-defined]
        self._clear_axe_transition_flags()
        if (
            worker_succeeded
            and operation in ("start", "restart")
            and not self.axe_running
        ):
            self._schedule_post_axe_worker_status_repolls()

    def _clear_axe_transition_flags(self) -> None:
        """Clear transient axe operation indicators after a worker completes."""
        self._set_axe_starting(False)  # type: ignore[attr-defined]
        self._set_axe_restarting(False)  # type: ignore[attr-defined]
        self._set_axe_stopping(False)  # type: ignore[attr-defined]

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
