"""Exit settlement and crash-loop notifications for the service host."""

from __future__ import annotations

import sys
import time
from typing import Any

from sase.procs import (
    ProcFinish,
    ProcSettlement,
    begin_proc_settlement,
    finish_proc,
)
from sase.procs.service_meta import SERVICE_PROC_MODE_DAEMON
from sase.service.config import ServiceConfigComposition
from sase.service.control import utc_timestamp
from sase.service.host_models import GivenUp as _GivenUp
from sase.service.host_models import PendingRestart as _PendingRestart
from sase.service.host_models import RunningProc as _RunningProc
from sase.service.host_support import (
    entry_signature as _entry_signature,
)
from sase.service.host_support import (
    terminal_status as _terminal_status,
)
from sase.service.notifications import (
    notify_service_crash_loop as _notify_crash_loop_event,
)
from sase.service.notifications import notify_service_give_up as _notify_give_up_event
from sase.service.paths import service_proc_output_log_path
from sase.service.restart import (
    ServiceExit,
    ServiceRestartDecision,
    decide_service_restart,
)
from sase.service.state import ServiceStateSnapshot
from sase.service.status import ServiceProcLastExit


class ServiceHostExitsMixin:
    """Settle reaped children and track restart decisions."""

    def _settle_exit(
        self: Any,
        name: str,
        running: _RunningProc,
        return_code: int,
        *,
        config: ServiceConfigComposition | None,
        state: ServiceStateSnapshot | None,
    ) -> None:
        exit_code = return_code if return_code >= 0 else None
        signum = -return_code if return_code < 0 else None
        status = (
            "killed"
            if running.stop_requested
            else _terminal_status(exit_code, running.entry.success_exit_codes)
        )
        message = (
            "stopped"
            if running.stop_requested
            else f"exited with code {exit_code}"
            if exit_code is not None
            else f"terminated by signal {signum}"
        )
        finished_at = time.time()
        last_exit = ServiceProcLastExit(
            exit_code=exit_code,
            signal=signum,
            finished_at=finished_at,
        )
        self._last_exits[name] = last_exit
        begin_proc_settlement(
            ProcSettlement(
                proc_id=running.proc_id,
                supervisor_id=running.supervisor_id,
                settling_at=utc_timestamp(),
                exit_code=exit_code,
                message=message,
            )
        )
        finish_proc(
            ProcFinish(
                proc_id=running.proc_id,
                supervisor_id=running.supervisor_id,
                status=status,
                finished_at=utc_timestamp(),
                exit_code=exit_code,
                message=message,
                result={"service": {"name": name, "mode": SERVICE_PROC_MODE_DAEMON}},
            )
        )

        decision = decide_service_restart(
            running.entry.restart,
            ServiceExit(
                exit_code=exit_code,
                signal=signum,
                stop_requested=running.stop_requested,
            ),
            running.restart_history,
            now=finished_at,
            success_exit_codes=running.entry.success_exit_codes,
        )
        self._restart_history[name] = decision.history
        self._restart_decisions[name] = decision
        if decision.action == "restart" and decision.restart_at is not None:
            current = config.get(name) if config is not None else running.entry
            if (
                current is not None
                and state is not None
                and self._desired_running(current, state)
            ):
                self._pending[name] = _PendingRestart(
                    entry=current,
                    signature=_entry_signature(current),
                    restart_at=decision.restart_at,
                    history=decision.history,
                    decision=decision,
                    restarts=running.restarts + 1,
                    last_exit=last_exit,
                )
        if decision.notify and not running.stop_requested:
            self._notify_crash_loop(name, decision, restarts=running.restarts + 1)
        if decision.action == "give_up" and not running.stop_requested:
            current = config.get(name) if config is not None else running.entry
            desired = (
                current is not None
                and state is not None
                and self._desired_running(current, state)
            )
            self._record_given_up(
                name,
                signature=running.signature,
                decision=decision,
                last_exit=last_exit,
                restarts=running.restarts,
                desired=desired,
            )

    def _notify_crash_loop(
        self: Any,
        name: str,
        decision: ServiceRestartDecision,
        *,
        restarts: int,
    ) -> None:
        """Upsert one durable row per crash-loop episode; never raises."""
        try:
            episode = self._notify_episodes.get(name, 0) + 1
            self._notify_episodes[name] = episode
            _notify_crash_loop_event(
                name=name,
                reason=decision.reason,
                restarts=restarts,
                log_path=str(service_proc_output_log_path(name)),
                host_started_at=self._started_at,
                episode=episode,
            )
        except Exception as exc:  # noqa: BLE001 - reconcile never breaks on notify.
            print(f"sase service host notification error: {exc}", file=sys.stderr)

    def _record_given_up(
        self: Any,
        name: str,
        *,
        signature: str,
        decision: ServiceRestartDecision,
        last_exit: ServiceProcLastExit,
        restarts: int,
        desired: bool,
    ) -> None:
        """Park a given-up proc until an explicit revive; notify when desired."""
        self._given_up[name] = _GivenUp(
            signature=signature,
            decision=decision,
            last_exit=last_exit,
            restarts=restarts,
            given_up_at=time.time(),
        )
        if not desired:
            return
        try:
            _notify_give_up_event(
                name=name,
                reason=decision.reason,
                restarts=restarts,
                log_path=str(service_proc_output_log_path(name)),
                host_started_at=self._started_at,
                episode=self._notify_episodes.get(name, 0),
            )
        except Exception as exc:  # noqa: BLE001 - reconcile never breaks on notify.
            print(f"sase service host notification error: {exc}", file=sys.stderr)
