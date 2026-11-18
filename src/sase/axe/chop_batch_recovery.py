"""Shared recovery entry point for interrupted chop launch batches.

Resume is continuation of the already accepted run: reconcile pending
manifests before routine guards, reuse the original run ID and agent
identities, and never rerun job scripts or allocate another clan. An
explicit clan-generation kill persists cancellation before any signal or
artifact work so recovery permanently discards the remaining intent.
"""

from ._chop_batch_recovery_cancel import cancel_chop_batches_for_clan
from ._chop_batch_recovery_observations import collect_spawn_observations
from ._chop_batch_recovery_queries import (
    has_unfinished_chop_batch,
    pending_batch_for_run,
)
from ._chop_batch_recovery_resume import (
    ChopBatchRecoveryResult,
    recover_pending_chop_batches,
)

__all__ = [
    "ChopBatchRecoveryResult",
    "cancel_chop_batches_for_clan",
    "collect_spawn_observations",
    "has_unfinished_chop_batch",
    "pending_batch_for_run",
    "recover_pending_chop_batches",
]
