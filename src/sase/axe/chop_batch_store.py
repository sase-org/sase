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

from ._chop_batch_store_batches import (
    apply_chop_batch_event,
    create_chop_batch,
    load_chop_batch,
    reconcile_stored_batch,
    summarize_stored_batch,
    update_chop_batch,
)
from ._chop_batch_store_lifecycle import (
    batch_has_unsettled_cancelled_dispatch,
    delete_archived_chop_batch,
    delete_chop_batch,
    list_chop_batches_for_clan,
    list_pending_chop_batches,
    release_and_retire_chop_batch,
    retire_chop_batch,
)
from ._chop_batch_store_notices import (
    chop_batch_dispatch_attempts,
    increment_chop_batch_dispatch_attempt,
    load_chop_batch_notice_state,
    pending_chop_batch_notices,
    update_chop_batch_notice_state,
)
from ._chop_batch_store_ownership import (
    acquire_chop_batch_ownership,
    read_chop_batch_owner,
)
from ._chop_batch_store_paths import (
    chop_batch_owner_path,
    chop_batch_path,
    chop_batches_dir,
    ensure_chop_batches_dir,
)
from ._chop_batch_store_shared import (
    CHOP_BATCH_ATTEMPTS_SUFFIX,
    CHOP_BATCH_DIRNAME,
    CHOP_BATCH_FILENAME_SUFFIX,
    CHOP_BATCH_MUTATION_LOCK_FILENAME,
    CHOP_BATCH_NOTICES_SUFFIX,
    CHOP_BATCH_OWNER_SUFFIX,
    CHOP_BATCH_OWNERSHIP_LOCK_FILENAME,
    MAX_PENDING_BATCHES,
    ChopBatchCorruptError,
    ChopBatchError,
    ChopBatchExistsError,
    ChopBatchNotFoundError,
)

__all__ = [
    "CHOP_BATCH_DIRNAME",
    "CHOP_BATCH_FILENAME_SUFFIX",
    "CHOP_BATCH_NOTICES_SUFFIX",
    "CHOP_BATCH_ATTEMPTS_SUFFIX",
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
    "batch_has_unsettled_cancelled_dispatch",
    "chop_batch_owner_path",
    "chop_batch_path",
    "chop_batches_dir",
    "create_chop_batch",
    "delete_chop_batch",
    "delete_archived_chop_batch",
    "chop_batch_dispatch_attempts",
    "increment_chop_batch_dispatch_attempt",
    "ensure_chop_batches_dir",
    "list_pending_chop_batches",
    "list_chop_batches_for_clan",
    "load_chop_batch",
    "load_chop_batch_notice_state",
    "pending_chop_batch_notices",
    "read_chop_batch_owner",
    "reconcile_stored_batch",
    "retire_chop_batch",
    "release_and_retire_chop_batch",
    "summarize_stored_batch",
    "update_chop_batch_notice_state",
    "update_chop_batch",
]
