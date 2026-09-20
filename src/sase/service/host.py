"""Foreground per-machine service host runtime."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from sase.procs import (
    ProcFinish,
    ProcReserve,
    ProcSettlement,
    ProcServiceBlock,
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
from sase.service.boot import current_boot_id
from sase.service.config import ServiceConfigComposition, ServiceProcConfig
from sase.service.config import load_service_config
from sase.service.control import utc_timestamp
from sase.service.host_lifecycle import run_host
from sase.service.host_models import PendingRestart as _PendingRestart
from sase.service.host_models import RunningProc as _RunningProc
from sase.service.host_reporting import write_current_host_status
from sase.service.host_support import (
    entry_env as _entry_env,
    entry_launch as _entry_launch,
    entry_signature as _entry_signature,
    handover_scheduler,
    package_version as _package_version,
    process_group as _process_group,
    pump_service_output as _pump_service_output,
    signal_number as _signal_number,
    terminal_status as _terminal_status,
)
from sase.service.paths import service_proc_dir, service_proc_output_log_path
from sase.service.restart import (
    ServiceExit,
    ServiceRestartDecision,
    ServiceRestartHistory,
    decide_service_restart,
)
from sase.service.state import (
    ServiceHostRecord,
    ServiceStateSnapshot,
    read_service_state,
    record_service_host,
)
from sase.service.status import (
    ServiceProcLastExit,
)

_RECONCILE_SECONDS = 1.0
_STOP_KILL_TIMEOUT_SECONDS = 5.0


class _ServiceHost:
    """Reconcile configured daemon service procs as direct children."""

    def __init__(self) -> None:
        self._running = True
        self._nudge = threading.Event()
        self._children: dict[str, _RunningProc] = {}
        self._pending: dict[str, _PendingRestart] = {}
        self._last_exits: dict[str, ServiceProcLastExit] = {}
        self._restart_history: dict[str, ServiceRestartHistory] = {}
        self._restart_decisions: dict[str, ServiceRestartDecision] = {}
        self._restart_counts: dict[str, int] = {}
        self._boot_id = current_boot_id()
        self._started_at = time.time()
        self._unit = os.environ.get("SASE_SERVICE_UNIT") or None
        self._warned_service_marker_dropped = False

    def run(self) -> int:
        """Run the foreground host until SIGTERM, SIGINT, or KeyboardInterrupt."""
        return run_host(self, _RECONCILE_SECONDS)

    def _record_heartbeat(self, *, error: str | None = None) -> None:
        record_service_host(
            ServiceHostRecord(
                pid=os.getpid(),
                boot_id=self._boot_id,
                started_at=self._started_at,
                heartbeat_at=time.time(),
                mode="foreground",
                unit=self._unit,
                sase_version=_package_version(),
                error=error,
            )
        )

    def _reconcile_once(self) -> None:
        error: str | None = None
        try:
            config = load_service_config()
            state = read_service_state()
            self._observe_exits(config, state)
            self._reconcile_desired(config, state)
            write_current_host_status(self, config, state)
        except Exception as exc:  # noqa: BLE001 - long-lived host must keep running.
            error = str(exc)
            try:
                write_current_host_status(self)
            except Exception:
                pass
            print(f"sase service host reconcile error: {exc}", file=sys.stderr)
        finally:
            self._record_heartbeat(error=error)

    def _observe_exits(
        self,
        config: ServiceConfigComposition,
        state: ServiceStateSnapshot,
    ) -> None:
        for name, running in list(self._children.items()):
            return_code = running.process.poll()
            if return_code is None:
                continue
            self._settle_exit(name, running, return_code, config=config, state=state)
            del self._children[name]

    def _settle_exit(
        self,
        name: str,
        running: _RunningProc,
        return_code: int,
        *,
        config: ServiceConfigComposition,
        state: ServiceStateSnapshot,
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
            current = config.get(name)
            if current is not None and self._desired_running(current, state):
                self._pending[name] = _PendingRestart(
                    entry=current,
                    signature=_entry_signature(current),
                    restart_at=decision.restart_at,
                    history=decision.history,
                    decision=decision,
                    restarts=running.restarts + 1,
                    last_exit=last_exit,
                )

    def _reconcile_desired(
        self,
        config: ServiceConfigComposition,
        state: ServiceStateSnapshot,
    ) -> None:
        entries = {entry.name: entry for entry in config.procs}
        for name in list(self._children):
            entry = entries.get(name)
            running = self._children[name]
            if (
                entry is None
                or not self._desired_running(entry, state)
                or _entry_signature(entry) != running.signature
            ):
                self._stop_child(name, running)
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

        for entry in config.procs:
            if entry.name in self._children or entry.name in self._pending:
                continue
            if self._desired_running(entry, state):
                self._launch(entry, history=self._restart_history.get(entry.name))

    def _desired_running(
        self,
        entry: ServiceProcConfig,
        state: ServiceStateSnapshot,
    ) -> bool:
        override = state.state.enablement.get(entry.name)
        enabled = entry.enabled if override is None else override.enabled
        return bool(entry.available and enabled and entry.name not in state.state.stops)

    def _launch(
        self,
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
        self, recorded: ProcServiceBlock | None
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
        self,
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

    def _record_spawn_failure(self, entry: ServiceProcConfig, error: str) -> None:
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

    def _stop_child(self, name: str, running: _RunningProc) -> None:
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
            state = read_service_state()
            config = load_service_config()
            self._settle_exit(name, running, return_code, config=config, state=state)

    def _stop_all_children(self) -> None:
        for name, running in list(self._children.items()):
            self._stop_child(name, running)
        self._children.clear()
        self._pending.clear()


def run_service_host() -> int:
    """Entry point used by ``sase service run``."""
    return _ServiceHost().run()


__all__ = ["_ServiceHost", "run_service_host"]
