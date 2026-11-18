"""Crash-safe persistent store for interrupted chop launch batches.

A batch manifest freezes the accepted concrete launch plan before the first
dispatch so a routine or service-host stop can resume the original identities
instead of replanning. The Rust batch contract in ``sase_core::axe_chop``
owns validation, transitions, resume selection, and counts; this module owns
filesystem layout, atomic durability, and process-safe ownership. It never
reimplements the state machine.

Lock order (outermost first): admission lock, agent-name lock, batch mutation
lock, batch ownership lock. The mutation lock serializes read/transform/write
cycles; the ownership lock is a separate, short-held lock so cancellation can
persist while a member launch is in flight. Both locks pair an in-process
mutex with a dedicated cross-process ``flock`` file.

Layout (outside the prunable run-history payloads)::

    ~/.sase/axe/lumberjacks/{routine}/chops/{job}/pending_batches/
        {batch_id}.batch.json
        {batch_id}.owner.json
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.core.axe_chop_facade import (
    CHOP_BATCH_SCHEMA_VERSION,
    apply_chop_batch_transition,
    reconcile_chop_batch,
    summarize_chop_batch,
    validate_chop_batch_manifest,
)

from .state import best_effort_test_state_write_allowed as _writes_allowed
from .state import lumberjack_state_dir

CHOP_BATCH_DIRNAME = "pending_batches"
CHOP_BATCH_FILENAME_SUFFIX = ".batch.json"
CHOP_BATCH_OWNER_SUFFIX = ".owner.json"
CHOP_BATCH_MUTATION_LOCK_FILENAME = "pending_batches.lock"
CHOP_BATCH_OWNERSHIP_LOCK_FILENAME = "pending_batches.ownership.lock"

#: Upper bound for one recovery scan; the directory holds one small manifest
#: per interrupted batch, so this cap only bites on corruption or misuse.
MAX_PENDING_BATCHES = 256

_MUTEXES_LOCK = threading.Lock()
_MUTEXES: dict[str, threading.Lock] = {}


class ChopBatchError(Exception):
    """Base error for chop batch store failures."""


class ChopBatchNotFoundError(ChopBatchError):
    """The requested batch manifest does not exist."""


class ChopBatchExistsError(ChopBatchError):
    """A batch manifest already exists for this batch id."""


class _ChopBatchOwnershipError(ChopBatchError):
    """A live executor already owns the batch being created."""


class ChopBatchCorruptError(ChopBatchError):
    """The stored batch manifest cannot be parsed or fails validation."""


def chop_batches_dir(routine: str, job: str) -> Path:
    """Return the pending-batch directory for one routine/job pair."""
    return lumberjack_state_dir(routine) / "chops" / job / CHOP_BATCH_DIRNAME


def chop_batch_path(routine: str, job: str, batch_id: str) -> Path:
    """Return the manifest path for one batch."""
    _require_safe_batch_id(batch_id)
    return chop_batches_dir(routine, job) / f"{batch_id}{CHOP_BATCH_FILENAME_SUFFIX}"


def chop_batch_owner_path(routine: str, job: str, batch_id: str) -> Path:
    """Return the executor-ownership sidecar path for one batch."""
    _require_safe_batch_id(batch_id)
    return chop_batches_dir(routine, job) / f"{batch_id}{CHOP_BATCH_OWNER_SUFFIX}"


def ensure_chop_batches_dir(routine: str, job: str) -> Path:
    """Create the pending-batch directory for one routine/job pair."""
    directory = chop_batches_dir(routine, job)
    if _writes_allowed(directory, category="axe-chop-state"):
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def create_chop_batch(
    routine: str,
    job: str,
    manifest: dict[str, Any],
    *,
    owner: str | None = None,
) -> dict[str, Any]:
    """Persist a new batch, optionally claiming it before it becomes visible."""
    try:
        validated = validate_chop_batch_manifest(manifest)
    except ValueError as exc:
        raise ChopBatchCorruptError(f"batch manifest failed validation: {exc}") from exc
    batch_id = str(validated["batch_id"])
    _require_safe_batch_id(batch_id)
    ensure_chop_batches_dir(routine, job)
    path = chop_batch_path(routine, job, batch_id)
    with _locked(_mutation_lock_path(routine, job)):
        if path.exists():
            raise ChopBatchExistsError(f"batch {batch_id!r} already exists")
        claimed = False
        if owner is not None:
            claimed = acquire_chop_batch_ownership(routine, job, batch_id, owner=owner)
            if not claimed:
                raise _ChopBatchOwnershipError(
                    f"batch {batch_id!r} already has a live executor"
                )
        try:
            _atomic_write_manifest(path, validated)
        except BaseException:
            if claimed:
                release_chop_batch_ownership(routine, job, batch_id)
            raise
    return validated


def load_chop_batch(routine: str, job: str, batch_id: str) -> dict[str, Any]:
    """Load and validate one batch manifest.

    Unknown schema versions and corrupt payloads raise
    :class:`ChopBatchCorruptError` so callers never dispatch from them.
    """
    path = chop_batch_path(routine, job, batch_id)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            raise ChopBatchNotFoundError(f"batch {batch_id!r} not found") from exc
        raise ChopBatchError(f"cannot read batch {batch_id!r}: {exc}") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ChopBatchCorruptError(
            f"batch {batch_id!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ChopBatchCorruptError(f"batch {batch_id!r} must be a JSON object")
    try:
        return validate_chop_batch_manifest(manifest)
    except ValueError as exc:
        raise ChopBatchCorruptError(
            f"batch {batch_id!r} failed validation: {exc}"
        ) from exc


def update_chop_batch(
    routine: str,
    job: str,
    batch_id: str,
    transform: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Atomically read, transform, validate, and rewrite one manifest."""
    ensure_chop_batches_dir(routine, job)
    path = chop_batch_path(routine, job, batch_id)
    with _locked(_mutation_lock_path(routine, job)):
        current = load_chop_batch(routine, job, batch_id)
        updated = transform(dict(current))
        if not isinstance(updated, dict):
            raise ChopBatchError("batch transform must return a manifest dict")
        try:
            validated = validate_chop_batch_manifest(updated)
        except ValueError as exc:
            raise ChopBatchCorruptError(
                f"batch {batch_id!r} update failed validation: {exc}"
            ) from exc
        _atomic_write_manifest(path, validated)
    return validated


def apply_chop_batch_event(
    routine: str,
    job: str,
    batch_id: str,
    event: str,
    *,
    member_index: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Apply one Rust-owned state-machine event to a stored manifest."""

    def _apply(manifest: dict[str, Any]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "schema_version": CHOP_BATCH_SCHEMA_VERSION,
            "manifest": manifest,
            "event": event,
        }
        if member_index is not None:
            request["member_index"] = member_index
        if reason is not None:
            request["reason"] = reason
        return apply_chop_batch_transition(request)

    try:
        return update_chop_batch(routine, job, batch_id, _apply)
    except ValueError as exc:
        raise ChopBatchError(f"cannot apply batch event {event!r}: {exc}") from exc


def summarize_stored_batch(routine: str, job: str, batch_id: str) -> dict[str, Any]:
    """Return batch identity plus progress counts for a stored manifest."""
    manifest = load_chop_batch(routine, job, batch_id)
    try:
        return summarize_chop_batch(manifest)
    except ValueError as exc:
        raise ChopBatchError(f"cannot summarize batch {batch_id!r}: {exc}") from exc


def reconcile_stored_batch(
    routine: str,
    job: str,
    batch_id: str,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Select the resume work for a stored batch from spawn observations."""
    manifest = load_chop_batch(routine, job, batch_id)
    try:
        return reconcile_chop_batch(
            {
                "schema_version": CHOP_BATCH_SCHEMA_VERSION,
                "manifest": manifest,
                "observations": list(observations),
            }
        )
    except ValueError as exc:
        raise ChopBatchError(f"cannot reconcile batch {batch_id!r}: {exc}") from exc


def list_pending_chop_batches(
    routine: str, job: str, *, limit: int = MAX_PENDING_BATCHES
) -> list[dict[str, Any]]:
    """Enumerate stored batch manifests, newest filename first.

    Corrupt or unreadable manifests are skipped so one bad file cannot block
    recovery of the rest; use :func:`load_chop_batch` to surface a single
    file's failure.
    """
    directory = chop_batches_dir(routine, job)
    try:
        candidates = sorted(
            (
                path
                for path in directory.iterdir()
                if path.name.endswith(CHOP_BATCH_FILENAME_SUFFIX)
            ),
            key=lambda path: path.name,
            reverse=True,
        )
    except OSError:
        return []
    batches: list[dict[str, Any]] = []
    for path in candidates[: max(0, limit)]:
        batch_id = path.name[: -len(CHOP_BATCH_FILENAME_SUFFIX)]
        try:
            batches.append(load_chop_batch(routine, job, batch_id))
        except ChopBatchError:
            continue
    return batches


def delete_chop_batch(routine: str, job: str, batch_id: str) -> bool:
    """Delete one batch manifest and its ownership sidecar."""
    manifest_path = chop_batch_path(routine, job, batch_id)
    owner_path = chop_batch_owner_path(routine, job, batch_id)
    with _locked(_mutation_lock_path(routine, job)):
        missing = not manifest_path.exists()
        for path in (manifest_path, owner_path):
            try:
                path.unlink()
            except OSError as exc:
                if exc.errno != errno.ENOENT:
                    raise ChopBatchError(
                        f"cannot delete batch {batch_id!r}: {exc}"
                    ) from exc
    return not missing


def acquire_chop_batch_ownership(
    routine: str, job: str, batch_id: str, *, owner: str | None = None
) -> bool:
    """Claim executor ownership of one batch.

    Returns ``True`` when this process now owns the batch. A live owner
    (its PID still exists) keeps ownership and this returns ``False``; a
    stale record from a dead process may be superseded. Only one executor
    can own a batch, so a second routine or manual caller leaves a live
    owner alone.
    """
    ensure_chop_batches_dir(routine, job)
    owner_path = chop_batch_owner_path(routine, job, batch_id)
    with _locked(_ownership_lock_path(routine, job)):
        current = _read_owner_record(owner_path)
        if current is not None and _pid_is_live(current.get("pid")):
            return False
        record: dict[str, Any] = {
            "batch_id": batch_id,
            "pid": os.getpid(),
            "owner": owner or f"pid:{os.getpid()}",
        }
        _atomic_write_manifest(owner_path, record)
        return True


def release_chop_batch_ownership(routine: str, job: str, batch_id: str) -> bool:
    """Release executor ownership held by this process."""
    owner_path = chop_batch_owner_path(routine, job, batch_id)
    with _locked(_ownership_lock_path(routine, job)):
        current = _read_owner_record(owner_path)
        if current is None:
            return False
        if current.get("pid") != os.getpid():
            return False
        try:
            owner_path.unlink()
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                raise ChopBatchError(
                    f"cannot release batch {batch_id!r}: {exc}"
                ) from exc
        return True


def read_chop_batch_owner(routine: str, job: str, batch_id: str) -> dict | None:
    """Return the current ownership record, if any."""
    return _read_owner_record(chop_batch_owner_path(routine, job, batch_id))


def _require_safe_batch_id(batch_id: str) -> None:
    if not batch_id or batch_id.strip() != batch_id or not batch_id.strip():
        raise ChopBatchError(f"invalid batch id {batch_id!r}")
    if "/" in batch_id or "\\" in batch_id or batch_id in {".", ".."}:
        raise ChopBatchError(f"invalid batch id {batch_id!r}")
    if len(batch_id) > 256:
        raise ChopBatchError(f"invalid batch id {batch_id!r}")


def _mutation_lock_path(routine: str, job: str) -> Path:
    return chop_batches_dir(routine, job) / CHOP_BATCH_MUTATION_LOCK_FILENAME


def _ownership_lock_path(routine: str, job: str) -> Path:
    return chop_batches_dir(routine, job) / CHOP_BATCH_OWNERSHIP_LOCK_FILENAME


def _mutex_for(key: str) -> threading.Lock:
    with _MUTEXES_LOCK:
        mutex = _MUTEXES.get(key)
        if mutex is None:
            mutex = threading.Lock()
            _MUTEXES[key] = mutex
        return mutex


class _locked:
    """Hold an in-process mutex plus an exclusive flock on a lock file."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._mutex = _mutex_for(str(lock_path))
        self._handle: Any = None

    def __enter__(self) -> _locked:
        self._mutex.acquire()
        try:
            if _writes_allowed(self._lock_path, category="axe-chop-state"):
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


def _atomic_write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write one manifest atomically with fsync durability."""
    if not _writes_allowed(path, category="axe-chop-state"):
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
        _fsync_dir(path.parent)
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


def _fsync_dir(directory: Path) -> None:
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


def _read_owner_record(path: Path) -> dict | None:
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


def _pid_is_live(pid: Any) -> bool:
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


__all__ = [
    "CHOP_BATCH_DIRNAME",
    "CHOP_BATCH_FILENAME_SUFFIX",
    "CHOP_BATCH_MUTATION_LOCK_FILENAME",
    "CHOP_BATCH_OWNER_SUFFIX",
    "CHOP_BATCH_OWNERSHIP_LOCK_FILENAME",
    "MAX_PENDING_BATCHES",
    "ChopBatchCorruptError",
    "ChopBatchError",
    "ChopBatchExistsError",
    "ChopBatchNotFoundError",
    "acquire_chop_batch_ownership",
    "apply_chop_batch_event",
    "chop_batch_owner_path",
    "chop_batch_path",
    "chop_batches_dir",
    "create_chop_batch",
    "delete_chop_batch",
    "ensure_chop_batches_dir",
    "list_pending_chop_batches",
    "load_chop_batch",
    "read_chop_batch_owner",
    "reconcile_stored_batch",
    "release_chop_batch_ownership",
    "summarize_stored_batch",
    "update_chop_batch",
]
