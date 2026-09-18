"""Foreground per-machine service host runtime."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from sase.ace.hooks.processes import is_process_running
from sase.config.core import set_include_local_config
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
    SERVICE_PROC_MODE_DAEMON,
    SERVICE_PROC_SOURCE_BUILTIN,
)
from sase.service.boot import current_boot_id
from sase.service.config import ServiceConfigComposition, ServiceProcConfig
from sase.service.config import load_service_config
from sase.service.control import ServiceHostLock, utc_timestamp
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
    clear_service_host,
    read_service_state,
    record_service_host,
)
from sase.service.status import (
    ServiceHostObservation,
    ServiceProcLastExit,
    ServiceProcObservation,
    ServiceProcReportedStatus,
    build_service_status,
    write_service_status,
)
from sase.supervision import pump_output

_RECONCILE_SECONDS = 1.0
_STATUS_REPORT_MAX_BYTES = 32 * 1024
_STOP_KILL_TIMEOUT_SECONDS = 5.0


@dataclass
class _RunningProc:
    entry: ServiceProcConfig
    signature: str
    process: subprocess.Popen[bytes]
    proc_id: str
    supervisor_id: str
    started_at: float
    stop_requested: bool = False
    restart_history: ServiceRestartHistory = field(
        default_factory=ServiceRestartHistory
    )
    restart_decision: ServiceRestartDecision | None = None
    last_exit: ServiceProcLastExit | None = None
    restarts: int = 0


@dataclass
class _PendingRestart:
    entry: ServiceProcConfig
    signature: str
    restart_at: float
    history: ServiceRestartHistory
    decision: ServiceRestartDecision
    restarts: int
    last_exit: ServiceProcLastExit | None


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

    def run(self) -> int:
        """Run the foreground host until SIGTERM, SIGINT, or KeyboardInterrupt."""
        set_include_local_config(False)
        lock = ServiceHostLock.acquire(blocking=False)
        if lock is None:
            print("sase service run: service host is already running", file=sys.stderr)
            return 1
        try:
            lock.write_holder_pid()
            self._install_signal_handlers()
            self._record_heartbeat()
            self._reconcile_once()
            while self._running:
                self._nudge.wait(_RECONCILE_SECONDS)
                self._nudge.clear()
                self._reconcile_once()
            self._stop_all_children()
            self._write_status()
            clear_service_host(os.getpid())
            return 0
        except KeyboardInterrupt:
            self._stop_all_children()
            clear_service_host(os.getpid())
            return 130
        finally:
            lock.release()

    def _install_signal_handlers(self) -> None:
        def shutdown(_signum: int, _frame: object) -> None:
            self._running = False
            self._nudge.set()

        def nudge(_signum: int, _frame: object) -> None:
            self._nudge.set()

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        if hasattr(signal, "SIGUSR1"):
            signal.signal(signal.SIGUSR1, nudge)

    def _record_heartbeat(self, *, error: str | None = None) -> None:
        record_service_host(
            ServiceHostRecord(
                pid=os.getpid(),
                boot_id=self._boot_id,
                started_at=self._started_at,
                heartbeat_at=time.time(),
                mode="foreground",
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
            self._write_status(config=config, state=state)
        except Exception as exc:  # noqa: BLE001 - long-lived host must keep running.
            error = str(exc)
            try:
                self._write_status()
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
            and not self._handover_scheduler(entry)
        ):
            self._record_spawn_failure(
                entry,
                "scheduler handover could not establish single ownership",
            )
            return

        try:
            argv = _entry_argv(entry)
        except Exception as exc:  # noqa: BLE001 - reconcile must keep running.
            self._record_spawn_failure(entry, str(exc))
            return
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
        reserve_proc(
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
                origin="service-host",
                tags=["service", f"service:{entry.name}"],
                log_owner="service-host",
                shell_kind="service",
                service=ProcServiceBlock(
                    name=entry.name,
                    mode=SERVICE_PROC_MODE_DAEMON,
                    source=entry.source or SERVICE_PROC_SOURCE_BUILTIN,
                ),
            )
        )
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
            self._finish_spawn_failure(proc_id, supervisor_id, entry, str(exc))
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

    def _handover_scheduler(self, _entry: ServiceProcConfig) -> bool:
        try:
            from sase.axe.lock import is_lifecycle_lock_held
            from sase.axe.process import stop_axe_daemon_result

            if not is_lifecycle_lock_held():
                return True
            result = stop_axe_daemon_result(record_desired_state=False, timeout=10.0)
            if result.error is not None or result.failed_pids:
                return False
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if not is_lifecycle_lock_held():
                    return True
                time.sleep(0.1)
            return False
        except Exception:
            return False

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

    def _write_status(
        self,
        *,
        config: ServiceConfigComposition | None = None,
        state: ServiceStateSnapshot | None = None,
    ) -> None:
        composition = load_service_config() if config is None else config
        state_snapshot = read_service_state() if state is None else state
        observations = [
            self._observation(name, running) for name, running in self._children.items()
        ]
        for name, pending in self._pending.items():
            if name in self._children:
                continue
            observations.append(
                ServiceProcObservation(
                    name=name,
                    alive=False,
                    last_exit=pending.last_exit,
                    restart=pending.decision,
                    restarts=pending.restarts,
                    log_path=str(service_proc_output_log_path(name)),
                )
            )
        snapshot = build_service_status(
            composition,
            state_snapshot,
            ServiceHostObservation(
                record=ServiceHostRecord(
                    pid=os.getpid(),
                    boot_id=self._boot_id,
                    started_at=self._started_at,
                    heartbeat_at=time.time(),
                    mode="foreground",
                    sase_version=_package_version(),
                ),
                lock_held=True,
                pid_alive=True,
            ),
            observations,
        )
        write_service_status(snapshot)

    def _observation(self, name: str, running: _RunningProc) -> ServiceProcObservation:
        return ServiceProcObservation(
            name=name,
            pid=running.process.pid
            if is_process_running(running.process.pid)
            else None,
            alive=running.process.poll() is None,
            proc_id=running.proc_id,
            started_at=running.started_at,
            last_exit=running.last_exit or self._last_exits.get(name),
            restart=running.restart_decision or self._restart_decisions.get(name),
            restarts=running.restarts,
            reported=_read_reported_status(name),
            log_path=str(service_proc_output_log_path(name)),
        )


def run_service_host() -> int:
    """Entry point used by ``sase service run``."""
    return _ServiceHost().run()


def _entry_argv(entry: ServiceProcConfig) -> tuple[str, ...]:
    launcher = entry.launcher
    if launcher is None:
        return ()
    if launcher.kind == "builtin":
        if launcher.builtin == "scheduler":
            return (*_sase_command(), "scheduler", "run")
        if launcher.builtin == "gateway":
            return _gateway_builtin_argv()
        return ()
    if launcher.argv:
        return tuple(launcher.argv)
    if isinstance(launcher.command, str):
        return ("/bin/sh", "-lc", launcher.command)
    return tuple(str(part) for part in launcher.command or ())


def _gateway_builtin_argv() -> tuple[str, ...]:
    from sase.integrations.mobile_gateway import prepare_mobile_gateway_service_launch

    return tuple(prepare_mobile_gateway_service_launch().argv)


def _entry_env(entry: ServiceProcConfig, proc_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key, value in entry.env.items():
        env[str(key)] = os.path.expandvars(str(value))
    env["SASE_SERVICE_PROC"] = entry.name
    env["SASE_SERVICE_PROC_DIR"] = str(proc_dir)
    env["SASE_SERVICE_PROC_STATUS"] = str(proc_dir / "status.json")
    return env


def _entry_signature(entry: ServiceProcConfig) -> str:
    payload = {
        "after": entry.after,
        "available": entry.available,
        "cwd": entry.cwd,
        "env": entry.env,
        "launcher": None
        if entry.launcher is None
        else {
            "argv": entry.launcher.argv,
            "builtin": entry.launcher.builtin,
            "command": entry.launcher.command,
            "kind": entry.launcher.kind,
        },
        "log_max_bytes": entry.log_max_bytes,
        "mode": entry.mode,
        "restart": entry.restart,
        "stop_signal": entry.stop_signal,
        "stop_timeout_seconds": entry.stop_timeout_seconds,
        "success_exit_codes": entry.success_exit_codes,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _read_reported_status(name: str) -> ServiceProcReportedStatus | None:
    path = service_proc_dir(name) / "status.json"
    try:
        if path.stat().st_size > _STATUS_REPORT_MAX_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    summary = str(payload.get("summary") or "").strip()
    state = str(payload.get("state") or "").strip()
    if not summary or not state:
        return None
    try:
        updated_at = float(payload.get("updated_at") or path.stat().st_mtime)
    except (TypeError, ValueError, OSError):
        updated_at = time.time()
    return ServiceProcReportedStatus(
        summary=summary[:200],
        state=state[:64],
        updated_at=updated_at,
    )


def _pump_service_output(
    stream: BinaryIO,
    log_path: Path,
    max_bytes: int,
) -> None:
    pump_output(stream, lambda chunk: _append_bounded_log(log_path, chunk, max_bytes))


def _append_bounded_log(path: Path, chunk: bytes, max_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(chunk)
    if max_bytes <= 0:
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= max_bytes:
        return
    with path.open("rb") as handle:
        handle.seek(max(0, size - max_bytes))
        data = handle.read()
    with path.open("wb") as handle:
        handle.write(data)


def _signal_number(name: str) -> int:
    if name.isdigit():
        return int(name)
    normalized = name if name.startswith("SIG") else f"SIG{name}"
    return int(getattr(signal, normalized, signal.SIGTERM))


def _terminal_status(exit_code: int | None, success_exit_codes: tuple[int, ...]) -> str:
    if exit_code == 0 or (exit_code is not None and exit_code in success_exit_codes):
        return "success"
    return "error"


def _process_group(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        return None


def _sase_command() -> tuple[str, ...]:
    invoked = Path(sys.argv[0])
    if invoked.name == "sase" and invoked.exists():
        return (str(invoked),)
    found = shutil.which("sase")
    if found is not None:
        return (found,)
    return (sys.executable, "-m", "sase")


def _package_version() -> str | None:
    try:
        from importlib.metadata import version

        return version("sase")
    except Exception:
        return None


__all__ = ["_ServiceHost", "run_service_host"]
