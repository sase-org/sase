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

from tests.ace.tui.visual._visual_capture_paths import atomic_write_text
from tests.ace.tui.visual._visual_maintenance_types import (
    CACHE_RELATIVE,
    LOCK_FILENAME,
    OverlappingRunError,
    RUNS_DIRNAME,
)


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

    def acquire(self, *, run_id: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            holder = _read_holder(self.path)
            os.close(fd)
            detail = f" ({holder})" if holder else ""
            raise OverlappingRunError(
                "another fix-tui-screenshots run holds the maintenance lock"
                f"{detail}; wait for it to finish rather than overwriting "
                "its scratch directory"
            ) from exc
        self._fd = fd
        _write_holder(fd, run_id=run_id)

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
    repo_root: Path, *, run_id: str
) -> Iterator[MaintenanceLock]:
    """Acquire the checkout-local lock or refuse an overlapping run."""
    held = MaintenanceLock(lock_path(repo_root))
    held.acquire(run_id=run_id)
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
