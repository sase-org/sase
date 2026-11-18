"""Executor ownership for crash-safe chop launch batches."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

from ._chop_batch_store_paths import (
    chop_batch_owner_path,
    ensure_chop_batches_dir,
    ownership_lock_path,
)
from ._chop_batch_store_shared import (
    ChopBatchError,
    atomic_write_manifest,
    locked,
    pid_is_live,
    read_owner_record,
)


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
    with locked(ownership_lock_path(routine, job)):
        current = read_owner_record(owner_path)
        if current is not None and pid_is_live(current.get("pid")):
            return False
        record: dict[str, Any] = {
            "batch_id": batch_id,
            "pid": os.getpid(),
            "owner": owner or f"pid:{os.getpid()}",
        }
        atomic_write_manifest(owner_path, record)
        return True


def release_chop_batch_ownership(routine: str, job: str, batch_id: str) -> bool:
    """Release executor ownership held by this process."""
    owner_path = chop_batch_owner_path(routine, job, batch_id)
    with locked(ownership_lock_path(routine, job)):
        current = read_owner_record(owner_path)
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
        released = True
    return released


def read_chop_batch_owner(routine: str, job: str, batch_id: str) -> dict | None:
    """Return the current ownership record, if any."""
    return read_owner_record(chop_batch_owner_path(routine, job, batch_id))
