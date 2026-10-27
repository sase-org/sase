"""Locking and lock-holder diagnostics for agents sidecar synchronization."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import fcntl
import json
import os
from pathlib import Path
import time

DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_TIMEOUT_ENV = "SASE_AGENTS_SYNC_LOCK_TIMEOUT"


@dataclass(frozen=True, slots=True)
class _SyncLockHolder:
    """One recorded ``bounded_agents_lock`` acquisition."""

    pid: int
    operation: str | None
    agent: str | None
    started_at: float


def _lock_holder_path(path: Path) -> Path:
    return path.parent / f"{path.name}.holder"


def _write_lock_holder(path: Path, *, operation: str | None = None) -> None:
    """Record this process as the lock holder beside the flock file.

    Best-effort: holder tracking must never fail a sync operation.
    """

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        holder = _SyncLockHolder(
            pid=os.getpid(),
            operation=operation,
            agent=os.environ.get("SASE_AGENT_NAME") or None,
            started_at=time.time(),
        )
        tmp_path = path.parent / f"{path.name}.holder.{os.getpid()}.tmp"
        tmp_path.write_text(
            json.dumps(
                {
                    "pid": holder.pid,
                    "operation": holder.operation,
                    "agent": holder.agent,
                    "started_at": holder.started_at,
                }
            ),
            encoding="utf-8",
        )
        os.replace(tmp_path, _lock_holder_path(path))
    except OSError:
        return


def _clear_lock_holder(path: Path) -> None:
    """Remove the holder record written by :func:`_write_lock_holder`."""

    try:
        _lock_holder_path(path).unlink(missing_ok=True)
    except OSError:
        return


def _holder_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def _read_lock_holder(path: Path) -> _SyncLockHolder | None:
    """Return the live holder record, ignoring stale or unreadable ones."""

    try:
        raw = _lock_holder_path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    pid = data.get("pid")
    started_at = data.get("started_at")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(started_at, (int, float)):
        return None
    if not _holder_pid_alive(pid):
        return None
    operation = data.get("operation")
    agent = data.get("agent")
    return _SyncLockHolder(
        pid=pid,
        operation=operation if isinstance(operation, str) else None,
        agent=agent if isinstance(agent, str) else None,
        started_at=float(started_at),
    )


def lock_holder_diagnostic(path: Path) -> str | None:
    """Describe the current lock holder for lock-busy error messages."""

    holder = _read_lock_holder(path)
    if holder is None:
        return None
    age = max(time.time() - holder.started_at, 0.0)
    parts = [f"pid {holder.pid}"]
    if holder.operation:
        parts.append(f"operation {holder.operation!r}")
    if holder.agent:
        parts.append(f"agent {holder.agent!r}")
    parts.append(f"age {age:.0f}s")
    return f"lock holder: {', '.join(parts)}"


@contextmanager
def bounded_agents_lock(
    path: Path,
    timeout_seconds: float,
    *,
    operation: str | None = None,
) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(0.05, max(deadline - time.monotonic(), 0.0)))
        if acquired:
            _write_lock_holder(path, operation=operation)
        yield acquired
    finally:
        if acquired:
            _clear_lock_holder(path)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def configured_agents_lock_timeout() -> float:
    raw = os.environ.get(_LOCK_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS
    return max(value, 0.0)
