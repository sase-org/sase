"""Observer lifecycle and projection support for proc actions."""

from __future__ import annotations

from typing import Any

from textual.worker import Worker

from ..proc_observer import (
    ObservedProc,
    ProcObserver,
    ProcProjection,
    compose_proc_projection,
)
from ..widgets.proc_indicator import MonitorIndicator, ProcIndicator
from ._proc_action_types import ProcCallbackConfig

PROC_RECONCILE_STARTUP_DELAY_SECONDS = 1.0
PROC_RECONCILE_INTERVAL_SECONDS = 30.0


class ProcObserverActionsMixin:
    """Manage the durable proc observer and its effective TUI projection."""

    def _init_proc_observer(self) -> None:
        """Initialize observer projection, short submit workers, and callbacks."""
        self._proc_projection = ProcProjection()
        self._durable_submit_workers: dict[str, Worker[Any]] = {}
        self._session_workers: dict[str, Worker[Any]] = {}
        self._session_completion_callbacks: dict[str, Any] = {}
        self._proc_completion_callbacks: dict[str, ProcCallbackConfig] = {}
        self._proc_pending_scopes: dict[str, frozenset[str]] = {}
        self._proc_session_id = _resolve_current_session_id()
        self._proc_reconciler_worker: Worker[Any] | None = None
        self._proc_reconciler_start_timer = None
        self._proc_reconciler_interval_timer = None
        self._proc_observer = ProcObserver(
            on_snapshot=self._on_proc_observer_thread_snapshot,  # type: ignore[attr-defined]
        )
        self._proc_observer.start()

    def _stop_proc_observer(self) -> None:
        """Retire the observer thread without touching proc lifetimes."""
        self._stop_proc_reconciler()
        observer = getattr(self, "_proc_observer", None)
        if observer is not None:
            observer.stop(timeout=1.0)

    def _start_proc_reconciler(self) -> None:
        """Start slow best-effort orphaned-proc reconciliation workers."""
        set_timer = getattr(self, "set_timer", None)
        set_interval = getattr(self, "set_interval", None)
        if callable(set_timer):
            self._proc_reconciler_start_timer = set_timer(
                PROC_RECONCILE_STARTUP_DELAY_SECONDS,
                self._run_proc_reconciler,
                name="proc-reconciler-start",
            )
        if callable(set_interval):
            self._proc_reconciler_interval_timer = set_interval(
                PROC_RECONCILE_INTERVAL_SECONDS,
                self._run_proc_reconciler,
                name="proc-reconciler",
            )

    def _stop_proc_reconciler(self) -> None:
        """Stop ACE-side proc reconciliation timers and worker."""
        for attr in (
            "_proc_reconciler_start_timer",
            "_proc_reconciler_interval_timer",
        ):
            timer = getattr(self, attr, None)
            setattr(self, attr, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass
        worker = getattr(self, "_proc_reconciler_worker", None)
        self._proc_reconciler_worker = None
        if worker is not None and getattr(worker, "is_running", False):
            try:
                worker.cancel()
            except Exception:
                pass

    def _run_proc_reconciler(self) -> None:
        """Run one orphaned-proc reconciliation pass in a thread worker."""
        worker = getattr(self, "_proc_reconciler_worker", None)
        if worker is not None and getattr(worker, "is_running", False):
            return
        from ..proc_reconciler import reconcile_running_procs_safely

        self._proc_reconciler_worker = self.run_worker(  # type: ignore[attr-defined]
            reconcile_running_procs_safely,
            thread=True,
            name="proc-reconciler",
            group="procs",
        )

    def _update_proc_indicator(self) -> None:
        """Update the proc and monitor indicators from the effective projection.

        Each widget is looked up and updated independently so a missing
        indicator (e.g. during widget setup/teardown) never blocks the other.
        """
        try:
            projection = self._effective_proc_projection()
        except Exception:
            return
        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#proc-indicator", ProcIndicator
            )
            indicator.set_count(
                projection.active_count - projection.active_monitor_count
            )
        except Exception:
            pass
        try:
            monitor_indicator = self.query_one(  # type: ignore[attr-defined]
                "#monitor-indicator", MonitorIndicator
            )
            monitor_indicator.set_count(projection.active_monitor_count)
        except Exception:
            pass

    def _session_overlay_rows(self) -> tuple[ObservedProc, ...]:
        """Return ObservedProc rows for currently running session workers."""
        rows: list[ObservedProc] = []
        for recorded in getattr(self, "_session_completion_callbacks", {}).values():
            if not isinstance(recorded, tuple) or len(recorded) != 2:
                continue
            _on_complete, proc_info = recorded
            if isinstance(proc_info, ObservedProc):
                rows.append(proc_info)
        return tuple(rows)

    def _effective_proc_projection(self) -> ProcProjection:
        """Compose durable observer rows with live session-local workers."""
        durable = getattr(self, "_proc_projection", ProcProjection())
        if not isinstance(durable, ProcProjection):
            durable = ProcProjection()
        return compose_proc_projection(durable, self._session_overlay_rows())


def _resolve_current_session_id() -> str | None:
    """Return the current ACE session id if the registry is readable."""
    try:
        from sase.sessions import current_session_id

        return current_session_id()
    except Exception:
        return None
