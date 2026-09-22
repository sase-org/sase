"""Checkout-local exclusive lock and unique run directories."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import time
import uuid

from collections.abc import Callable

from tests.ace.tui.visual._visual_capture_paths import atomic_write_text
from tests.ace.tui.visual._visual_maintenance_types import (
    CACHE_RELATIVE,
    LOCK_FILENAME,
    MaintenanceHooks,
    OverlappingRunError,
    RUNS_DIRNAME,
)


DEFAULT_LOCK_TIMEOUT_SECONDS = 2 * 60 * 60
DEFAULT_LOCK_POLL_INTERVAL_SECONDS = 1.0
LOCK_NOTICE_INTERVAL_SECONDS = 60.0


def cache_root(repo_root: Path) -> Path:
    """Return ``.pytest_cache/sase-visual`` under *repo_root*."""
    return repo_root / CACHE_RELATIVE


def lock_path(repo_root: Path) -> Path:
    """Return the exclusive maintenance lock path."""
    return cache_root(repo_root) / LOCK_FILENAME


def new_run_id() -> str:
    """Return a unique maintenance run identity."""
    return uuid.uuid4().hex


def create_run_dir(repo_root: Path, run_id: str) -> Path:
    """Create a unique run directory; refuse if the path already exists."""
    path = cache_root(repo_root) / RUNS_DIRNAME / run_id
    if path.exists():
        raise OverlappingRunError(f"run directory already exists: {path}")
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_run_record(run_dir: Path, payload: dict[str, object]) -> Path:
    """Atomically write ``run.json`` under *run_dir*."""
    path = run_dir / "run.json"
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


class MaintenanceLock:
    """Non-blocking exclusive lock for one checkout's screenshot maintenance."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(
        self,
        *,
        run_id: str,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        """Acquire the lock, waiting (bounded) while another run holds it."""
        timeout = (
            DEFAULT_LOCK_TIMEOUT_SECONDS
            if timeout_seconds is None
            else max(0.0, float(timeout_seconds))
        )
        poll = (
            DEFAULT_LOCK_POLL_INTERVAL_SECONDS
            if poll_interval_seconds is None
            else max(0.0, float(poll_interval_seconds))
        )
        sleep_fn = time.sleep if sleep is None else sleep
        clock = time.monotonic if monotonic is None else monotonic
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = clock() + timeout
        waiting = False
        last_notice = 0.0
        while True:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
            else:
                self._fd = fd
                _write_holder(fd, run_id=run_id)
                return
            holder = _read_holder(self.path)
            now = clock()
            if now >= deadline:
                detail = f" ({holder})" if holder else ""
                raise OverlappingRunError(
                    "another fix-tui-screenshots run holds the maintenance lock"
                    f"{detail}; gave up waiting after {timeout:g}s "
                    "rather than overwriting its scratch directory"
                )
            if not waiting or now - last_notice >= LOCK_NOTICE_INTERVAL_SECONDS:
                detail = f"held by {holder}" if holder else "held by another run"
                print(
                    "waiting for the maintenance lock "
                    f"({detail}); will wait up to {timeout:g}s",
                    flush=True,
                )
                waiting = True
                last_notice = now
            sleep_fn(min(poll, max(0.0, deadline - now)))

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
            self._fd = None


@contextmanager
def exclusive_maintenance_lock(
    repo_root: Path,
    *,
    run_id: str,
    hooks: MaintenanceHooks | None = None,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> Iterator[MaintenanceLock]:
    """Acquire the checkout-local lock, waiting (bounded) on overlap."""
    if timeout_seconds is None and hooks is not None:
        timeout_seconds = hooks.lock_timeout_seconds
    if poll_interval_seconds is None and hooks is not None:
        poll_interval_seconds = hooks.lock_poll_interval_seconds
    held = MaintenanceLock(lock_path(repo_root))
    held.acquire(
        run_id=run_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        sleep=sleep,
        monotonic=monotonic,
    )
    try:
        yield held
    finally:
        held.release()


def _write_holder(fd: int, *, run_id: str) -> None:
    payload = (
        json.dumps(
            {
                "pid": os.getpid(),
                "run_id": run_id,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, payload.encode("utf-8"))
    os.fsync(fd)


def _read_holder(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return " ".join(text.split())
