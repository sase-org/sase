"""Service-host control, probing, and CLI-facing status helpers."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.detach_scope import detach_scope
from sase.feature_flags import FeatureFlag, current_flags
from sase.procs import ACTIVE_PROC_STATUSES, TERMINAL_PROC_STATUSES, read_procs
from sase.service.config import ServiceConfigComposition, load_service_config
from sase.service.paths import (
    service_host_lock_path,
    service_host_log_path,
    service_host_start_lock_path,
    service_proc_output_log_path,
)
from sase.service.state import ServiceHostRecord, read_service_state
from sase.service.status import (
    ServiceHostObservation,
    ServiceProcLastExit,
    ServiceProcObservation,
    ServiceStatusSnapshot,
    build_service_status,
    read_service_status,
)

SERVICE_HOST_DISABLED_MESSAGE = (
    "service_host beta flag is disabled; enable it for this invocation with "
    "`sase -f service_host service ...`."
)
_HOST_STALE_SECONDS = 15.0
_START_WAIT_SECONDS = 15.0
_STOP_WAIT_SECONDS = 15.0
_POLL_SECONDS = 0.1


class ServiceHostDisabledError(RuntimeError):
    """Raised when a beta-gated service command is used with the flag off."""


@dataclass(frozen=True)
class _ServiceHostProbe:
    """Current best-effort host observation."""

    record: ServiceHostRecord | None
    lock_held: bool
    pid_alive: bool | None

    @property
    def running(self) -> bool:
        return bool(self.lock_held or (self.record and self.pid_alive))


@dataclass(frozen=True)
class _ServiceHostActionResult:
    """Human and machine result for one host lifecycle action."""

    ok: bool
    changed: bool
    message: str
    pid: int | None = None


class ServiceHostLock:
    """Exclusive flock held for the entire foreground host lifetime."""

    def __init__(self, fd: int) -> None:
        self._fd: int | None = fd

    @classmethod
    def acquire(cls, *, blocking: bool) -> ServiceHostLock | None:
        path = service_host_lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flags)
        except OSError:
            os.close(fd)
            if not blocking:
                return None
            raise
        return cls(fd)

    @property
    def fd(self) -> int:
        if self._fd is None:
            raise RuntimeError("service host lock is closed")
        return self._fd

    def write_holder_pid(self, pid: int | None = None) -> None:
        holder = os.getpid() if pid is None else pid
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.ftruncate(self.fd, 0)
        os.write(self.fd, f"{holder}\n".encode("ascii"))
        os.fsync(self.fd)

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> ServiceHostLock:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.release()


def _service_host_enabled() -> bool:
    """Return the current process' beta-flag decision for the service host."""
    return current_flags().enabled(FeatureFlag.service_host)


def require_service_host_enabled(command: str) -> None:
    """Fail with a concise opt-in diagnostic when the beta flag is disabled."""
    if _service_host_enabled():
        return
    del command
    raise ServiceHostDisabledError(SERVICE_HOST_DISABLED_MESSAGE)


def _probe_service_host() -> _ServiceHostProbe:
    """Return lock, PID, and heartbeat observations for the host."""
    try:
        state = read_service_state().state
    except Exception:
        state = None
    record = None if state is None else state.host
    lock_held = _is_service_host_lock_held()
    pid_alive = None if record is None else is_process_running(record.pid)
    return _ServiceHostProbe(record=record, lock_held=lock_held, pid_alive=pid_alive)


def _is_service_host_lock_held() -> bool:
    """Return True when any process owns the service-host lifetime lock."""
    lock = ServiceHostLock.acquire(blocking=False)
    if lock is None:
        return True
    lock.release()
    return False


def nudge_service_host() -> bool:
    """Send a reconcile nudge to the host when a live PID is known."""
    probe = _probe_service_host()
    if probe.record is None or not probe.pid_alive:
        return False
    try:
        os.kill(probe.record.pid, signal.SIGUSR1)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def start_service_host(
    *, wait_seconds: float = _START_WAIT_SECONDS
) -> _ServiceHostActionResult:
    """Launch ``sase service run`` detached and wait for a fresh heartbeat."""
    with _short_file_lock(service_host_start_lock_path()):
        before = time.time()
        probe = _probe_service_host()
        if probe.record and probe.pid_alive:
            return _ServiceHostActionResult(
                ok=True,
                changed=False,
                message=f"service host is already running (pid {probe.record.pid})",
                pid=probe.record.pid,
            )
        if probe.lock_held:
            running = _wait_for_fresh_host(before, wait_seconds=wait_seconds)
            if running.record is not None:
                return _ServiceHostActionResult(
                    ok=True,
                    changed=False,
                    message=(
                        f"service host is already running (pid {running.record.pid})"
                    ),
                    pid=running.record.pid,
                )
            return _ServiceHostActionResult(
                ok=False,
                changed=False,
                message="service host lock is held but no fresh heartbeat appeared",
            )

        argv = [*_sase_command(), "service", "run"]
        command = detach_scope(
            argv,
            description="SASE service host",
            unit_prefix="sase-service",
            start_new_session=True,
        )
        log_path = service_host_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["SASE_FEATURE_FLAGS"] = _feature_env_with_service_host(env)
        with log_path.open("ab") as log:
            subprocess.Popen(
                command.argv,
                cwd=str(Path.cwd()),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=command.start_new_session,
                close_fds=True,
            )

        running = _wait_for_fresh_host(before, wait_seconds=wait_seconds)
        if running.record is None:
            return _ServiceHostActionResult(
                ok=False,
                changed=True,
                message="service host did not publish a fresh heartbeat",
            )
        return _ServiceHostActionResult(
            ok=True,
            changed=True,
            message="running detached (no platform unit installed)",
            pid=running.record.pid,
        )


def stop_service_host(
    *, wait_seconds: float = _STOP_WAIT_SECONDS
) -> _ServiceHostActionResult:
    """Signal the foreground service host and wait for it to exit."""
    probe = _probe_service_host()
    if probe.record is None or not probe.pid_alive:
        return _ServiceHostActionResult(
            ok=True,
            changed=False,
            message="service host is not running",
        )
    pid = probe.record.pid
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError) as exc:
        return _ServiceHostActionResult(
            ok=False,
            changed=False,
            message=f"could not signal service host {pid}: {exc}",
            pid=pid,
        )
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if not is_process_running(pid):
            return _ServiceHostActionResult(
                ok=True,
                changed=True,
                message=f"stopped service host {pid}",
                pid=pid,
            )
        time.sleep(_POLL_SECONDS)
    return _ServiceHostActionResult(
        ok=False,
        changed=True,
        message=f"service host {pid} did not stop before timeout",
        pid=pid,
    )


def restart_service_host() -> _ServiceHostActionResult:
    """Stop then start the host, verifying each side of the handoff."""
    stopped = stop_service_host()
    if not stopped.ok:
        return stopped
    started = start_service_host()
    return _ServiceHostActionResult(
        ok=started.ok,
        changed=stopped.changed or started.changed,
        message=started.message,
        pid=started.pid,
    )


def current_service_status(
    *,
    config: ServiceConfigComposition | None = None,
) -> ServiceStatusSnapshot:
    """Return a useful service snapshot even when the host is down."""
    composition = load_service_config() if config is None else config
    state_snapshot = read_service_state()
    probe = _probe_service_host()
    return build_service_status(
        composition,
        state_snapshot,
        ServiceHostObservation(
            record=probe.record,
            lock_held=probe.lock_held,
            pid_alive=probe.pid_alive,
            stale_after_seconds=_HOST_STALE_SECONDS,
        ),
        _proc_observations(),
    )


def persisted_or_current_status() -> ServiceStatusSnapshot:
    """Prefer a live host snapshot, falling back to a freshly derived one."""
    snapshot = read_service_status()
    if (
        snapshot is not None
        and time.time() - snapshot.generated_at <= _HOST_STALE_SECONDS
    ):
        return snapshot
    return current_service_status()


def latest_service_log_lines(path: Path, *, lines: int) -> str:
    """Read the tail of a bounded service log."""
    if lines <= 0:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _proc_observations() -> list[ServiceProcObservation]:
    observations: dict[str, ServiceProcObservation] = {}
    try:
        procs = read_procs()
    except Exception:
        return []
    for proc in procs:
        if proc.service is None or not proc.service.name:
            continue
        name = proc.service.name
        if name in observations:
            continue
        alive = proc.status in ACTIVE_PROC_STATUSES and (
            proc.pid is not None and is_process_running(proc.pid)
        )
        last_exit = None
        if proc.status in TERMINAL_PROC_STATUSES:
            last_exit = ServiceProcLastExit(
                exit_code=proc.exit_code,
                finished_at=_parse_timestamp(proc.finished_at),
                spawn_error=proc.message if proc.status == "error" else None,
            )
        observations[name] = ServiceProcObservation(
            name=name,
            pid=proc.pid if alive else None,
            alive=alive,
            proc_id=proc.proc_id,
            started_at=_parse_timestamp(proc.started_at),
            last_exit=last_exit,
            log_path=str(service_proc_output_log_path(name)),
        )
    return list(observations.values())


def _wait_for_fresh_host(
    since: float,
    *,
    wait_seconds: float,
) -> _ServiceHostProbe:
    deadline = time.monotonic() + wait_seconds
    last = _probe_service_host()
    while time.monotonic() < deadline:
        last = _probe_service_host()
        if (
            last.record is not None
            and last.record.heartbeat_at >= since
            and (last.pid_alive or last.lock_held)
        ):
            return last
        time.sleep(_POLL_SECONDS)
    return last


def _short_file_lock(path: Path) -> ServiceHostLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return ServiceHostLock(fd)


def _sase_command() -> list[str]:
    invoked = Path(sys.argv[0])
    if invoked.name == "sase" and invoked.exists():
        return [str(invoked)]
    found = shutil.which("sase")
    if found is not None:
        return [found]
    return [sys.executable, "-m", "sase"]


def _feature_env_with_service_host(env: dict[str, str]) -> str:
    raw = env.get("SASE_FEATURE_FLAGS", "").strip()
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["service_host"] = True
    return json.dumps(data, sort_keys=True)


def _parse_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def utc_timestamp() -> str:
    """Return the proc-store timestamp format used by service-host rows."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "SERVICE_HOST_DISABLED_MESSAGE",
    "ServiceHostDisabledError",
    "ServiceHostLock",
    "current_service_status",
    "latest_service_log_lines",
    "nudge_service_host",
    "persisted_or_current_status",
    "require_service_host_enabled",
    "restart_service_host",
    "start_service_host",
    "stop_service_host",
    "utc_timestamp",
]
