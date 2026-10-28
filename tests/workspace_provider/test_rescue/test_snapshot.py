"""Verified snapshot capture and restore tests.

This module re-exports the focused test groups to preserve the original import path.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.workspace_provider._snapshot_model import SourceState
from sase.workspace_provider.snapshot import (
    PreservationError,
    SnapshotRecord,
    restore_git_snapshot,
    snapshot_git_repo,
    snapshot_source_fingerprint,
)
from tests.workspace_provider.test_rescue._helpers import (
    commit_file,
    git,
    init_repo,
    redirect_state,
    rescue_entries,
    seed_remote_clone,
)
from tests.workspace_provider.test_rescue._snapshot_capture_tests import (
    test_published_snapshot_carries_local_commits_and_dirty_edits,
    test_published_snapshot_fails_before_worktree_write_when_base_is_unavailable,
    test_published_snapshot_thins_a_large_checkout_and_restores_exact_state,
    test_snapshot_refuses_non_git_path,
    test_snapshot_restores_tracked_and_untracked,
    test_snapshot_returns_none_when_checkout_is_clean,
    test_snapshot_without_remote_is_self_contained_and_legacy_manifest_restores,
)
from tests.workspace_provider.test_rescue._snapshot_conflict_tests import (
    test_snapshot_restores_conflict_stages_and_worktree_bytes,
    test_snapshot_restores_delete_modify_and_add_conflict_shapes,
)
from tests.workspace_provider.test_rescue._snapshot_failure_tests import (
    payload_module,
    payload_objects_module,
    source_module,
    test_snapshot_capture_failure_leaves_source_and_prior_snapshot,
    test_snapshot_detects_source_change_during_capture,
    test_snapshot_detects_untracked_source_change_during_capture,
    test_snapshot_ids_are_unique_for_same_head_and_timestamp,
    test_snapshot_manifest_failure_does_not_publish,
    test_snapshot_size_cap_fails_closed,
    test_snapshot_source_fingerprint_tracks_untracked_bytes,
)
from tests.workspace_provider.test_rescue._snapshot_index_tests import (
    payload_trees_module,
    test_snapshot_captures_assume_unchanged_and_skip_worktree_edits,
    test_snapshot_excludes_gitlink_commits_from_pack_and_restore,
    test_snapshot_hashes_only_dirty_candidates_in_a_large_clean_index,
    test_snapshot_restores_deletion_binary_and_tracked_ignored,
    test_snapshot_restores_staged_only_and_distinct_versions,
)

__all__ = [
    "Any",
    "Path",
    "PreservationError",
    "SnapshotRecord",
    "SourceState",
    "commit_file",
    "git",
    "init_repo",
    "json",
    "os",
    "payload_module",
    "payload_objects_module",
    "payload_trees_module",
    "pytest",
    "redirect_state",
    "rescue_entries",
    "restore_git_snapshot",
    "seed_remote_clone",
    "snapshot_git_repo",
    "snapshot_source_fingerprint",
    "source_module",
    "stat",
    "subprocess",
    "test_published_snapshot_carries_local_commits_and_dirty_edits",
    "test_published_snapshot_fails_before_worktree_write_when_base_is_unavailable",
    "test_published_snapshot_thins_a_large_checkout_and_restores_exact_state",
    "test_snapshot_capture_failure_leaves_source_and_prior_snapshot",
    "test_snapshot_captures_assume_unchanged_and_skip_worktree_edits",
    "test_snapshot_detects_source_change_during_capture",
    "test_snapshot_detects_untracked_source_change_during_capture",
    "test_snapshot_excludes_gitlink_commits_from_pack_and_restore",
    "test_snapshot_hashes_only_dirty_candidates_in_a_large_clean_index",
    "test_snapshot_ids_are_unique_for_same_head_and_timestamp",
    "test_snapshot_manifest_failure_does_not_publish",
    "test_snapshot_refuses_non_git_path",
    "test_snapshot_restores_conflict_stages_and_worktree_bytes",
    "test_snapshot_restores_delete_modify_and_add_conflict_shapes",
    "test_snapshot_restores_deletion_binary_and_tracked_ignored",
    "test_snapshot_restores_staged_only_and_distinct_versions",
    "test_snapshot_restores_tracked_and_untracked",
    "test_snapshot_returns_none_when_checkout_is_clean",
    "test_snapshot_size_cap_fails_closed",
    "test_snapshot_source_fingerprint_tracks_untracked_bytes",
    "test_snapshot_without_remote_is_self_contained_and_legacy_manifest_restores",
]
