"""Machine-owned commit reconciliation helpers for ``builtin@commit`` (facade).

These used to live on the deprecated ``run_commit_finalizer`` orchestrator.
The generic controller still needs auto-commit, bead publication, and
clean-result classification, so they sit behind this built-in-finalizer API.
"""

from __future__ import annotations

from sase.finalizers.reconciliation_auto_commit import (
    auto_commit_done_plan_status_if_possible as auto_commit_done_plan_status_if_possible,
    auto_commit_external_sdd_prompt_qa_if_possible as auto_commit_external_sdd_prompt_qa_if_possible,
    auto_commit_sdd_bead_reprojection_if_possible as auto_commit_sdd_bead_reprojection_if_possible,
)
from sase.finalizers.reconciliation_bead_store import (
    auto_commit_separate_sdd_store_if_possible as auto_commit_separate_sdd_store_if_possible,
    bead_sidecar_reconcile_diagnostic as bead_sidecar_reconcile_diagnostic,
)
from sase.finalizers.reconciliation_guard import (
    reject_unproven_reconciliation_transition as reject_unproven_reconciliation_transition,
)
from sase.finalizers.reconciliation_outcome import (
    clean_result_reason as clean_result_reason,
)
from sase.finalizers.reconciliation_state import (
    PreparedCommitDirtyState as PreparedCommitDirtyState,
    pre_reconciliation_dirty_state as pre_reconciliation_dirty_state,
    pre_reconciliation_fingerprints as pre_reconciliation_fingerprints,
    prepare_commit_dirty_state as prepare_commit_dirty_state,
)

__all__ = [
    "PreparedCommitDirtyState",
    "auto_commit_done_plan_status_if_possible",
    "auto_commit_external_sdd_prompt_qa_if_possible",
    "auto_commit_sdd_bead_reprojection_if_possible",
    "auto_commit_separate_sdd_store_if_possible",
    "bead_sidecar_reconcile_diagnostic",
    "clean_result_reason",
    "pre_reconciliation_dirty_state",
    "pre_reconciliation_fingerprints",
    "prepare_commit_dirty_state",
    "reject_unproven_reconciliation_transition",
]
