"""Read-only queries over pending chop recovery batches."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import chop_batch_store
from ._chop_batch_recovery_shared import batch_needs_resume
from .chop_batch_store import ChopBatchError


def has_unfinished_chop_batch(routine: str, job: str) -> bool:
    """Return whether any stored batch still owns pending dispatch work."""
    try:
        batches = chop_batch_store.list_pending_chop_batches(
            routine, job, repair_index=False, retire_terminal=False
        )
    except Exception:
        return False
    for manifest in batches:
        if batch_needs_resume(manifest):
            return True
    return False


def pending_batch_for_run(routine: str, job: str, run_id: str) -> dict[str, Any] | None:
    """Return a run batch while it has pending or in-flight dispatch work."""
    try:
        manifest = chop_batch_store.load_chop_batch(routine, job, run_id)
    except ChopBatchError:
        return None
    if not batch_needs_resume(manifest) and not _has_dispatching_member(manifest):
        return None
    return manifest


def _has_dispatching_member(manifest: Mapping[str, Any]) -> bool:
    members = manifest.get("members")
    return isinstance(members, list) and any(
        str(item.get("status") or "pending") == "dispatching"
        for item in members
        if isinstance(item, Mapping)
    )
