"""Filesystem layout for crash-safe chop launch batches."""

from __future__ import annotations

from pathlib import Path

from .state import best_effort_test_state_write_allowed, lumberjack_state_dir
from ._chop_batch_store_shared import (
    CHOP_BATCH_ATTEMPTS_SUFFIX,
    CHOP_BATCH_DIRNAME,
    CHOP_BATCH_FILENAME_SUFFIX,
    CHOP_BATCH_MUTATION_LOCK_FILENAME,
    CHOP_BATCH_NOTICES_SUFFIX,
    CHOP_BATCH_OWNER_SUFFIX,
    CHOP_BATCH_OWNERSHIP_LOCK_FILENAME,
    require_safe_batch_id,
)


def chop_batches_dir(routine: str, job: str) -> Path:
    """Return the pending-batch directory for one routine/job pair."""
    return lumberjack_state_dir(routine) / "chops" / job / CHOP_BATCH_DIRNAME


def chop_batch_path(routine: str, job: str, batch_id: str) -> Path:
    """Return the manifest path for one batch."""
    require_safe_batch_id(batch_id)
    return chop_batches_dir(routine, job) / f"{batch_id}{CHOP_BATCH_FILENAME_SUFFIX}"


def chop_batch_owner_path(routine: str, job: str, batch_id: str) -> Path:
    """Return the executor-ownership sidecar path for one batch."""
    require_safe_batch_id(batch_id)
    return chop_batches_dir(routine, job) / f"{batch_id}{CHOP_BATCH_OWNER_SUFFIX}"


def chop_batch_notices_path(routine: str, job: str, batch_id: str) -> Path:
    """Return the durable notification outbox beside one batch manifest."""
    require_safe_batch_id(batch_id)
    return chop_batches_dir(routine, job) / f"{batch_id}{CHOP_BATCH_NOTICES_SUFFIX}"


def chop_batch_attempts_path(routine: str, job: str, batch_id: str) -> Path:
    """Return recovery attempt metadata beside one batch manifest."""
    require_safe_batch_id(batch_id)
    return chop_batches_dir(routine, job) / f"{batch_id}{CHOP_BATCH_ATTEMPTS_SUFFIX}"


def archived_chop_batch_path(routine: str, job: str, batch_id: str) -> Path:
    """Return the run-history copy of a settled batch manifest."""
    require_safe_batch_id(batch_id)
    return (
        lumberjack_state_dir(routine)
        / "chops"
        / job
        / "runs"
        / f"{batch_id}{CHOP_BATCH_FILENAME_SUFFIX}"
    )


def clan_batch_index_path() -> Path:
    return lumberjack_state_dir("") / "pending_batches_by_clan.json"


def clan_batch_index_lock_path() -> Path:
    return lumberjack_state_dir("") / "pending_batches_by_clan.lock"


def mutation_lock_path(routine: str, job: str) -> Path:
    return chop_batches_dir(routine, job) / CHOP_BATCH_MUTATION_LOCK_FILENAME


def ownership_lock_path(routine: str, job: str) -> Path:
    return chop_batches_dir(routine, job) / CHOP_BATCH_OWNERSHIP_LOCK_FILENAME


def ensure_chop_batches_dir(routine: str, job: str) -> Path:
    """Create the pending-batch directory for one routine/job pair."""
    directory = chop_batches_dir(routine, job)
    if best_effort_test_state_write_allowed(directory, category="axe-chop-state"):
        directory.mkdir(parents=True, exist_ok=True)
    return directory
