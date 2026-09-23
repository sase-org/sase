"""Desired-state convergence and proc requests for the service host."""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from sase.service.config import ServiceConfigComposition, ServiceProcConfig
from sase.service.host_support import entry_signature as _entry_signature
from sase.service.restart import ServiceRestartHistory
from sase.service.state import ServiceStateSnapshot, complete_service_proc_request


class ServiceHostReconcileMixin:
    """Converge running children toward the desired configured state."""

    def _reconcile_desired(
        self: Any,
        config: ServiceConfigComposition,
        state: ServiceStateSnapshot,
    ) -> None:
        entries = {entry.name: entry for entry in config.procs}
        for name in list(self._given_up):
            entry = entries.get(name)
            if (
                entry is None
                or not self._desired_running(entry, state)
                or _entry_signature(entry) != self._given_up[name].signature
            ):
                del self._given_up[name]
        for name in list(self._children):
            entry = entries.get(name)
            running = self._children[name]
            if (
                entry is None
                or not self._desired_running(entry, state)
                or _entry_signature(entry) != running.signature
            ):
                self._stop_child(name, running, config, state)
                self._children.pop(name, None)
                self._pending.pop(name, None)

        for name in list(self._pending):
            entry = entries.get(name)
            pending = self._pending[name]
            if entry is None or not self._desired_running(entry, state):
                del self._pending[name]
                continue
            if _entry_signature(entry) != pending.signature:
                del self._pending[name]
                self._launch(entry, history=pending.history, restarts=pending.restarts)
                continue
            if time.time() >= pending.restart_at:
                del self._pending[name]
                self._launch(
                    entry,
                    history=pending.history,
                    restarts=pending.restarts,
                    last_exit=pending.last_exit,
                )

        self._consume_proc_requests(config, state)

        for entry in config.procs:
            if entry.name in self._children or entry.name in self._pending:
                continue
            given = self._given_up.get(entry.name)
            if given is not None and given.signature == _entry_signature(entry):
                continue
            if self._desired_running(entry, state):
                self._launch(entry, history=self._restart_history.get(entry.name))

    def _consume_proc_requests(
        self: Any,
        config: ServiceConfigComposition,
        state: ServiceStateSnapshot,
    ) -> None:
        """Consume pending start/restart requests before the launch loop."""
        entries = {entry.name: entry for entry in config.procs}
        for name, request in state.state.requests.items():
            if request.completed:
                continue
            try:
                self._consume_one_proc_request(
                    name, request.generation, request.action, entries, state
                )
            except Exception as exc:  # noqa: BLE001 - one bad name stops no loop.
                print(
                    f"sase service host: failed to consume {request.action} "
                    f"request for {name!r}: {exc}",
                    file=sys.stderr,
                )

    def _consume_one_proc_request(
        self: Any,
        name: str,
        generation: int,
        action: str,
        entries: dict[str, ServiceProcConfig],
        state: ServiceStateSnapshot,
    ) -> None:
        completed_by = f"service-host:{os.getpid()}"

        def _complete(
            *,
            pid: int | None = None,
            outcome: str | None = None,
            error: str | None = None,
        ) -> None:
            complete_service_proc_request(
                name,
                generation,
                pid=pid,
                outcome=outcome,
                error=error,
                actor=completed_by,
            )

        if action not in ("start", "restart"):
            _complete(
                outcome="failed",
                error=f"unknown service proc request action {action!r}",
            )
            return
        entry = entries.get(name)
        if entry is None:
            _complete(
                outcome="unknown_proc",
                error=f"unknown service proc {name!r}",
            )
            return
        if not self._desired_running(entry, state):
            _complete(
                outcome="not_desired",
                error=self._not_desired_reason(name, entry, state),
            )
            self._pending.pop(name, None)
            return
        # An explicit request starts a new episode: backoff and alert state
        # go back to clean, and any pending backoff restart is dropped.
        # It also revives a parked give-up for the same proc.
        self._pending.pop(name, None)
        self._given_up.pop(name, None)
        self._restart_history[name] = ServiceRestartHistory()
        running = self._children.get(name)
        if action == "start" and running is not None:
            _complete(outcome="already_running", pid=running.process.pid)
            return
        if action == "restart":
            stopped = self._children.pop(name, None)
            if stopped is not None:
                self._stop_child(name, stopped, None, state)
        self._launch(entry, history=ServiceRestartHistory())
        self._pending.pop(name, None)
        child = self._children.get(name)
        if child is None:
            last_exit = self._last_exits.get(name)
            error = (
                last_exit.spawn_error
                if last_exit is not None and last_exit.spawn_error
                else "service host could not launch the proc"
            )
            _complete(outcome="failed", error=error)
            return
        _complete(
            outcome="restarted" if action == "restart" else "started",
            pid=child.process.pid,
        )

    def _not_desired_reason(
        self: Any,
        name: str,
        entry: ServiceProcConfig,
        state: ServiceStateSnapshot,
    ) -> str:
        if name in state.state.stops:
            return f"service proc {name!r} is stopped until the next boot"
        override = state.state.enablement.get(name)
        enabled = entry.enabled if override is None else override.enabled
        if not enabled:
            return f"service proc {name!r} is disabled on this machine"
        return f"service proc {name!r} is unavailable"

    def _desired_running(
        self: Any,
        entry: ServiceProcConfig,
        state: ServiceStateSnapshot,
    ) -> bool:
        override = state.state.enablement.get(entry.name)
        enabled = entry.enabled if override is None else override.enabled
        return bool(entry.available and enabled and entry.name not in state.state.stops)
