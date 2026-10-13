"""Coverage for raw local-commit detection and absorption.

An agent's raw ``git commit`` outside the host stitch path leaves a clean
tree, so dirty-state discovery never sees it. The detector
(:func:`unrecorded_local_commits`) finds those commits from the run-start
baseline ``head``; :func:`absorb_raw_local_commits` soft-resets eligible
chains back to staged dirt; the execution-time backstop fails anything left
over with ``unpublished_local_commits`` (bead sase-1kh.2).

The tests are split into focused modules; this facade preserves the original
module's public imports and pytest collection path.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.finalizers.commit_types import BuiltinCommitFinalizerError
from sase.finalizers.commit_validation import raise_if_unpublished_local_commits
from sase.finalizers.ledger import RETRYABLE_DIAGNOSTIC_CODES
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider import commit_finalizer_raw_commits as raw_commits
from sase.llm_provider.commit_finalizer_baseline import (
    FINALIZER_BASELINE_FILENAME,
    capture_opened_repo_dirty_baseline,
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_raw_commits import (
    absorb_raw_local_commits,
    unrecorded_local_commits,
)
from sase.llm_provider.types import InvokeResult

from ._commit_finalizer_raw_commits_detection_tests import (
    test_detects_raw_commits_in_main_and_sibling_oldest_first,
    test_foreign_agent_commit_is_not_raw,
    test_host_stitch_commit_waiting_on_resume_is_not_raw,
    test_opened_repo_baseline_capture_records_head,
    test_own_and_unattributed_commits_are_still_raw_alongside_foreign,
    test_remote_reachable_fast_forwards_since_baseline_are_ignored,
    test_sdd_and_headless_baseline_records_are_skipped,
)
from ._commit_finalizer_raw_commits_absorb_tests import (
    test_absorb_revalidates_head_before_pinning_and_resetting,
    test_absorb_skips_detached_head,
    test_absorb_skips_merge_chain,
    test_absorb_skips_operation_in_progress,
    test_absorb_soft_resets_eligible_chain_and_is_idempotent,
    test_absorb_without_run_id_leaves_repos_untouched,
)
from ._commit_finalizer_raw_commits_protected_tests import (
    test_absorb_preserves_commit_before_complete_raw_suffix,
    test_absorb_rejects_filtered_commit_inside_raw_suffix,
    test_absorb_rejects_protected_path_restored_to_baseline_head,
    test_absorb_rejects_rename_of_a_protected_path,
    test_absorb_skips_raw_commit_of_baseline_dirty_path,
)
from ._commit_finalizer_raw_commits_backstop_tests import (
    test_backstop_fails_with_unpublished_local_commits,
    test_backstop_passes_when_no_unrecorded_commits,
    test_context_absorbs_eligible_raw_commit_into_obligation,
)

__all__ = [
    "BuiltinCommitFinalizerError",
    "FINALIZER_BASELINE_FILENAME",
    "InvokeResult",
    "Path",
    "RETRYABLE_DIAGNOSTIC_CODES",
    "absorb_raw_local_commits",
    "capture_opened_repo_dirty_baseline",
    "finalizer_git",
    "json",
    "load_finalizer_baseline_records",
    "pytest",
    "raise_if_unpublished_local_commits",
    "raw_commits",
    "subprocess",
    "test_absorb_preserves_commit_before_complete_raw_suffix",
    "test_absorb_rejects_filtered_commit_inside_raw_suffix",
    "test_absorb_rejects_protected_path_restored_to_baseline_head",
    "test_absorb_rejects_rename_of_a_protected_path",
    "test_absorb_revalidates_head_before_pinning_and_resetting",
    "test_absorb_skips_detached_head",
    "test_absorb_skips_merge_chain",
    "test_absorb_skips_operation_in_progress",
    "test_absorb_skips_raw_commit_of_baseline_dirty_path",
    "test_absorb_soft_resets_eligible_chain_and_is_idempotent",
    "test_absorb_without_run_id_leaves_repos_untouched",
    "test_backstop_fails_with_unpublished_local_commits",
    "test_backstop_passes_when_no_unrecorded_commits",
    "test_context_absorbs_eligible_raw_commit_into_obligation",
    "test_detects_raw_commits_in_main_and_sibling_oldest_first",
    "test_foreign_agent_commit_is_not_raw",
    "test_host_stitch_commit_waiting_on_resume_is_not_raw",
    "test_opened_repo_baseline_capture_records_head",
    "test_own_and_unattributed_commits_are_still_raw_alongside_foreign",
    "test_remote_reachable_fast_forwards_since_baseline_are_ignored",
    "test_sdd_and_headless_baseline_records_are_skipped",
    "unrecorded_local_commits",
]
