"""Read-only queries over pending chop recovery batches."""

from __future__ import annotations

from typing import Any

from . import chop_batch_store
from ._chop_batch_recovery_shared import batch_needs_resume
from .chop_batch_store import ChopBatchError


def has_unfinished_chop_batch(routine: str, job: str) -> bool:
    """Return whether any stored batch still owns pending dispatch work."""
    try:
        batches = chop_batch_store.list_pending_chop_batches(routine, job)
    except Exception:
        return False
    for manifest in batches:
        if batch_needs_resume(manifest):
            return True
    return False


def pending_batch_for_run(routine: str, job: str, run_id: str) -> dict[str, Any] | None:
    """Return the stored batch for one run, if it still owns dispatch work."""
    try:
        manifest = chop_batch_store.load_chop_batch(routine, job, run_id)
    except ChopBatchError:
        return None
    if not batch_needs_resume(manifest):
        return None
    return manifest
