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
from sase.service.host_models import GivenUp as _GivenUp
from sase.service.host_models import PendingRestart as _PendingRestart
from sase.service.host_models import RunningProc as _RunningProc
from sase.service.notifications import (
    notify_service_crash_loop as _notify_crash_loop_event,
)
from sase.service.notifications import notify_service_give_up as _notify_give_up_event
from sase.service.host_reporting import (
    empty_service_config,
    write_current_host_status,
)
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
from sase.service.platform_models import SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE
from sase.service.platform_runner import service_lifecycle_blocked_in_tests
from sase.service.restart import (
    ServiceExit,
    ServiceRestartDecision,
    ServiceRestartHistory,
    decide_service_restart,
)
from sase.service.state import (
    ServiceHostRecord,
    ServiceStateSnapshot,
    complete_service_proc_request,
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
        self._last_good_config: ServiceConfigComposition | None = None
        self._config_error: str | None = None
        self._given_up: dict[str, _GivenUp] = {}
        self._notify_episodes: dict[str, int] = {}

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
        heartbeat_error: str | None = None
        config: ServiceConfigComposition | None
        try:
            try:
                config = load_service_config()
                self._last_good_config = config
                self._config_error = None
            except Exception as exc:  # noqa: BLE001 - degraded host keeps supervising.
                heartbeat_error = str(exc)
                self._config_error = heartbeat_error
                config = self._last_good_config
                print(
                    f"sase service host config error: {exc} "
                    "— supervising last-known-good config",
                    file=sys.stderr,
                )
            try:
                state = read_service_state()
            except Exception as exc:  # noqa: BLE001 - host must keep heartbeating.
                if heartbeat_error is None:
                    heartbeat_error = str(exc)
                print(f"sase service host reconcile error: {exc}", file=sys.stderr)
                return
            if config is None:
                try:
                    self._observe_exits(None, state)
                    write_current_host_status(
                        self,
                        empty_service_config(),
                        state,
                        config_error=heartbeat_error,
                    )
                except Exception as exc:  # noqa: BLE001 - host must keep running.
                    if heartbeat_error is None:
                        heartbeat_error = str(exc)
                    print(f"sase service host reconcile error: {exc}", file=sys.stderr)
                return
            try:
                self._observe_exits(config, state)
                self._reconcile_desired(config, state)
                write_current_host_status(
                    self, config, state, config_error=heartbeat_error
                )
            except Exception as exc:  # noqa: BLE001 - host must keep running.
                if heartbeat_error is None:
                    heartbeat_error = str(exc)
                try:
                    write_current_host_status(
                        self, config, state, config_error=heartbeat_error
                    )
                except Exception:
                    pass
                print(f"sase service host reconcile error: {exc}", file=sys.stderr)
        finally:
            try:
                self._record_heartbeat(error=heartbeat_error)
            except Exception:  # noqa: BLE001 - heartbeat must not kill the host.
                pass

    def _observe_exits(
        self,
        config: ServiceConfigComposition | None,
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
        self,
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
        self,
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

    def _reconcile_desired(
        self,
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
        self,
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
        self,
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
        self,
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
        self,
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

    def _stop_all_children(self) -> None:
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


def run_service_host() -> int:
    """Entry point used by ``sase service run``."""
    if service_lifecycle_blocked_in_tests():
        print(SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE, file=sys.stderr)
        return 125
    return _ServiceHost().run()


__all__ = ["_ServiceHost", "run_service_host"]
