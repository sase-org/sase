"""Shared constants, errors, and crash-safe IO for chop batch store."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .state import best_effort_test_state_write_allowed

CHOP_BATCH_DIRNAME = "pending_batches"
CHOP_BATCH_FILENAME_SUFFIX = ".batch.json"
CHOP_BATCH_OWNER_SUFFIX = ".owner.json"
CHOP_BATCH_NOTICES_SUFFIX = ".notices.json"
CHOP_BATCH_ATTEMPTS_SUFFIX = ".attempts.json"
CHOP_BATCH_MUTATION_LOCK_FILENAME = "pending_batches.lock"
CHOP_BATCH_OWNERSHIP_LOCK_FILENAME = "pending_batches.ownership.lock"

#: Upper bound for one recovery scan; the directory holds one small manifest
#: per interrupted batch, so this cap only bites on corruption or misuse.
MAX_PENDING_BATCHES = 256
MAX_CLAN_BATCH_INDEX_ENTRIES = 256

_MUTEXES_LOCK = threading.Lock()
_MUTEXES: dict[str, threading.Lock] = {}


class ChopBatchError(Exception):
    """Base error for chop batch store failures."""


class ChopBatchNotFoundError(ChopBatchError):
    """The requested batch manifest does not exist."""


class ChopBatchExistsError(ChopBatchError):
    """A batch manifest already exists for this batch id."""


class ChopBatchCorruptError(ChopBatchError):
    """The stored batch manifest cannot be parsed or fails validation."""


def require_safe_batch_id(batch_id: str) -> None:
    if not batch_id or batch_id.strip() != batch_id or not batch_id.strip():
        raise ChopBatchError(f"invalid batch id {batch_id!r}")
    if "/" in batch_id or "\\" in batch_id or batch_id in {".", ".."}:
        raise ChopBatchError(f"invalid batch id {batch_id!r}")
    if len(batch_id) > 256:
        raise ChopBatchError(f"invalid batch id {batch_id!r}")


def _mutex_for(key: str) -> threading.Lock:
    with _MUTEXES_LOCK:
        mutex = _MUTEXES.get(key)
        if mutex is None:
            mutex = threading.Lock()
            _MUTEXES[key] = mutex
        return mutex


class locked:
    """Hold an in-process mutex plus an exclusive flock on a lock file."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._mutex = _mutex_for(str(lock_path))
        self._handle: Any = None

    def __enter__(self) -> locked:
        self._mutex.acquire()
        try:
            if best_effort_test_state_write_allowed(
                self._lock_path, category="axe-chop-state"
            ):
                self._lock_path.parent.mkdir(parents=True, exist_ok=True)
                self._handle = open(self._lock_path, "a+b")  # noqa: PTH123
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        except BaseException:
            self._mutex.release()
            raise
        return self

    def __exit__(self, *exc_info: Any) -> None:
        try:
            if self._handle is not None:
                try:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
                finally:
                    self._handle.close()
        finally:
            self._handle = None
            self._mutex.release()


def atomic_write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write one manifest atomically with fsync durability."""
    if not best_effort_test_state_write_allowed(path, category="axe-chop-state"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            json.dump(manifest, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
        fsync_dir(path.parent)
    except OSError as exc:
        raise ChopBatchError(f"cannot write batch file {path}: {exc}") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def fsync_dir(directory: Path) -> None:
    """Fsync a directory so creations and renames survive a crash."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_owner_record(path: Path) -> dict | None:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return None
        raise ChopBatchError(f"cannot read owner file {path}: {exc}") from exc
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def pid_is_live(pid: Any) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
