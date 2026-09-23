"""Child launch and shutdown for the foreground service host."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from sase.procs import (
    ProcFinish,
    ProcReserve,
    ProcServiceBlock,
    ProcSettlement,
    ProcSupervisorClaim,
    begin_proc_settlement,
    claim_proc_supervisor,
    finish_proc,
    new_proc_id,
    reserve_proc,
)
from sase.procs.models import COMMAND_PROC_KIND
from sase.procs.service_meta import (
    SERVICE_HOST_ORIGIN,
    SERVICE_PROC_MODE_DAEMON,
    SERVICE_PROC_SOURCE_BUILTIN,
)
from sase.service.config import ServiceConfigComposition, ServiceProcConfig
from sase.service.control import utc_timestamp
from sase.service.host_models import PendingRestart as _PendingRestart
from sase.service.host_models import RunningProc as _RunningProc
from sase.service.host_support import (
    entry_env as _entry_env,
)
from sase.service.host_support import (
    entry_launch as _entry_launch,
)
from sase.service.host_support import (
    entry_signature as _entry_signature,
)
from sase.service.host_support import (
    handover_scheduler,
    process_group as _process_group,
    pump_service_output as _pump_service_output,
    signal_number as _signal_number,
)
from sase.service.paths import service_proc_dir, service_proc_output_log_path
from sase.service.restart import (
    ServiceExit,
    ServiceRestartDecision,
    ServiceRestartHistory,
    decide_service_restart,
)
from sase.service.state import ServiceStateSnapshot
from sase.service.status import ServiceProcLastExit

_STOP_KILL_TIMEOUT_SECONDS = 5.0


class ServiceHostSpawnMixin:
    """Launch configured procs as direct children and stop them."""

    def _launch(
        self: Any,
        entry: ServiceProcConfig,
        *,
        history: ServiceRestartHistory | None,
        restarts: int = 0,
        last_exit: ServiceProcLastExit | None = None,
    ) -> None:
        if entry.launcher is None:
            self._record_spawn_failure(entry, "service entry has no launcher")
            return
        if (
            entry.launcher.kind == "builtin"
            and entry.launcher.builtin == "scheduler"
            and not handover_scheduler()
        ):
            self._record_spawn_failure(
                entry,
                "scheduler handover could not establish single ownership",
            )
            return

        try:
            launch = _entry_launch(entry)
        except Exception as exc:  # noqa: BLE001 - reconcile must keep running.
            self._record_spawn_failure(entry, str(exc))
            return
        argv = launch.argv
        if not argv:
            self._record_spawn_failure(entry, "service entry has no command")
            return
        cwd = str(Path(entry.cwd or Path.cwd()).expanduser())
        proc_dir = service_proc_dir(entry.name)
        proc_dir.mkdir(parents=True, exist_ok=True)
        log_path = service_proc_output_log_path(entry.name)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = _entry_env(entry, proc_dir)
        proc_id = new_proc_id()
        supervisor_id = f"service-host:{os.getpid()}:{proc_id}"
        service_block = ProcServiceBlock(
            name=entry.name,
            mode=SERVICE_PROC_MODE_DAEMON,
            source=entry.source or SERVICE_PROC_SOURCE_BUILTIN,
        )
        outcome = reserve_proc(
            ProcReserve(
                proc_id=proc_id,
                label=f"service:{entry.name}",
                argv=list(argv),
                cwd=cwd,
                created_at=utc_timestamp(),
                log_path=str(log_path),
                request_fingerprint=f"service:{entry.name}:{time.time_ns()}",
                reserved_by=f"service-host:{os.getpid()}",
                kind=COMMAND_PROC_KIND,
                origin=SERVICE_HOST_ORIGIN,
                tags=["service", f"service:{entry.name}"],
                log_owner="service-host",
                shell_kind="service",
                service=service_block,
            )
        )
        self._warn_if_service_marker_dropped(outcome.proc.service)
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            error = str(exc)
            if launch.diagnostic is not None:
                # Keep the OS text intact and say why the name did not resolve.
                error = f"{error}; {launch.diagnostic}"
            self._finish_spawn_failure(proc_id, supervisor_id, entry, error)
            return

        pgid = _process_group(process.pid)
        claim_proc_supervisor(
            ProcSupervisorClaim(
                proc_id=proc_id,
                supervisor_id=supervisor_id,
                claimed_at=utc_timestamp(),
                pid=process.pid,
                pgid=pgid,
            )
        )
        if process.stdout is not None:
            thread = threading.Thread(
                target=_pump_service_output,
                args=(process.stdout, log_path, entry.log_max_bytes),
                daemon=True,
            )
            thread.start()
        started_at = time.time()
        launch_history = history or ServiceRestartHistory()
        launch_history = ServiceRestartHistory(
            started_at=started_at,
            backoff_seconds=launch_history.backoff_seconds,
            consecutive_failures=launch_history.consecutive_failures,
            recent_failures=launch_history.recent_failures,
            alert_sent=launch_history.alert_sent,
        )
        self._children[entry.name] = _RunningProc(
            entry=entry,
            signature=_entry_signature(entry),
            process=process,
            proc_id=proc_id,
            supervisor_id=supervisor_id,
            started_at=started_at,
            restart_history=launch_history,
            last_exit=last_exit,
            restarts=restarts,
        )
        self._restart_history[entry.name] = launch_history
        self._restart_counts[entry.name] = restarts

    def _warn_if_service_marker_dropped(
        self: Any, recorded: ProcServiceBlock | None
    ) -> None:
        """Warn once per host process when the store dropped the service marker.

        A ``sase_core_rs`` build that predates the service proc wire metadata
        drops the additive ``service`` field without error. The launch still
        proceeds (readers fall back to the row's origin), but the operator is
        told why the marker is missing.
        """
        if recorded is not None or self._warned_service_marker_dropped:
            return
        self._warned_service_marker_dropped = True
        print(
            "sase service host: the proc store dropped the service marker from a "
            "reserved row; the loaded sase_core_rs build likely predates the "
            "service proc wire metadata. Rebuild or update sase-core and restart "
            "the service host.",
            file=sys.stderr,
        )

    def _finish_spawn_failure(
        self: Any,
        proc_id: str,
        supervisor_id: str,
        entry: ServiceProcConfig,
        error: str,
    ) -> None:
        claim_proc_supervisor(
            ProcSupervisorClaim(
                proc_id=proc_id,
                supervisor_id=supervisor_id,
                claimed_at=utc_timestamp(),
            )
        )
        begin_proc_settlement(
            ProcSettlement(
                proc_id=proc_id,
                supervisor_id=supervisor_id,
                settling_at=utc_timestamp(),
                message=error,
            )
        )
        finish_proc(
            ProcFinish(
                proc_id=proc_id,
                supervisor_id=supervisor_id,
                status="error",
                finished_at=utc_timestamp(),
                message=error,
                result={"service": {"name": entry.name, "spawn_error": error}},
            )
        )
        self._record_spawn_failure(entry, error)

    def _record_spawn_failure(self: Any, entry: ServiceProcConfig, error: str) -> None:
        now = time.time()
        last_exit = ServiceProcLastExit(spawn_error=error, finished_at=now)
        self._last_exits[entry.name] = last_exit
        history = self._restart_history.get(entry.name, ServiceRestartHistory())
        decision = decide_service_restart(
            entry.restart,
            ServiceExit(spawn_error=error),
            history,
            now=now,
            success_exit_codes=entry.success_exit_codes,
        )
        self._restart_history[entry.name] = decision.history
        self._restart_decisions[entry.name] = decision
        if decision.action == "restart" and decision.restart_at is not None:
            self._pending[entry.name] = _PendingRestart(
                entry=entry,
                signature=_entry_signature(entry),
                restart_at=decision.restart_at,
                history=decision.history,
                decision=decision,
                restarts=self._restart_counts.get(entry.name, 0) + 1,
                last_exit=last_exit,
            )
        if decision.notify:
            self._notify_crash_loop(
                entry.name,
                decision,
                restarts=self._restart_counts.get(entry.name, 0) + 1,
            )
        if decision.action == "give_up":
            self._record_given_up(
                entry.name,
                signature=_entry_signature(entry),
                decision=decision,
                last_exit=last_exit,
                restarts=self._restart_counts.get(entry.name, 0),
                desired=True,
            )

    def _stop_child(
        self: Any,
        name: str,
        running: _RunningProc,
        config: ServiceConfigComposition | None = None,
        state: ServiceStateSnapshot | None = None,
    ) -> None:
        running.stop_requested = True
        sig = _signal_number(running.entry.stop_signal)
        pid = running.process.pid
        try:
            pgid = os.getpgid(pid)
        except (ProcessLookupError, PermissionError, OSError):
            pgid = None
        try:
            if pgid is not None:
                os.killpg(pgid, sig)
            else:
                os.kill(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        deadline = time.monotonic() + running.entry.stop_timeout_seconds
        while time.monotonic() < deadline:
            if running.process.poll() is not None:
                break
            time.sleep(0.05)
        if running.process.poll() is None:
            try:
                if pgid is not None:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                running.process.wait(timeout=_STOP_KILL_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        return_code = running.process.poll()
        if return_code is not None:
            self._settle_exit(name, running, return_code, config=config, state=state)

    def _stop_all_children(self: Any) -> None:
        for name, running in list(self._children.items()):
            try:
                self._stop_child(name, running, None, None)
            except Exception as exc:  # noqa: BLE001 - shutdown stops every child.
                print(
                    f"sase service host stop error for {name!r}: {exc}",
                    file=sys.stderr,
                )
        self._children.clear()
        self._pending.clear()
