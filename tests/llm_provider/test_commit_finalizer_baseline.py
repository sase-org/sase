"""Coverage for the commit finalizer's pre-existing dirty-path baseline.

The tests are split into focused modules; this facade preserves the original
module's public imports and pytest collection path.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.finalizers.commit_validation import protected_baseline_paths
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_baseline import (
    BASELINE_FILENAME,
    FINALIZER_BASELINE_FILENAME,
    capture_dirty_baseline,
    capture_opened_repo_dirty_baseline,
    load_dirty_baseline,
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_git import (
    dirty_path_fingerprints,
    split_pre_existing_changed_files,
)
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.sdd.store import SDD_STORAGE_SIDECAR_REPOS, SddStore
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    init_git_repo,
    set_agent_env,
    set_clean_main,
)

from ._commit_finalizer_baseline_capture_tests import (
    test_capture_records_clean_sdd_sidecar_before_late_open,
    test_capture_records_head_for_run_start_repo,
    test_capture_writes_fingerprints_for_dirty_paths,
    test_late_open_baseline_capture_first_path_wins,
    test_late_open_baseline_capture_first_repo_id_wins,
    test_legacy_baseline_record_without_head_parses_and_skips_detection,
    test_split_pre_existing_changed_files_requires_matching_hash,
)
from ._commit_finalizer_baseline_dirty_tests import (
    test_baseline_dirty_file_edited_again_stays_in_must_commit_set,
    test_capture_writes_no_baseline_when_dirty_state_collection_fails,
    test_clean_baseline_does_not_affect_files_dirtied_after_capture,
    test_continuation_run_finalizer_commits_inherited_starters_work,
    test_corrupt_baseline_file_degrades_to_no_baseline,
    test_missing_baseline_file_behaves_like_no_baseline,
    test_pre_existing_main_file_is_excluded_and_reported_separately,
    test_pre_existing_sibling_file_is_excluded_and_reported_separately,
)
from ._commit_finalizer_baseline_records_tests import (
    test_finalizer_baseline_views_share_scope_and_duplicate_path_contract,
    test_historical_opened_repo_baseline_views_agree,
    test_load_dirty_baseline_reads_historical_legacy_file_only,
    test_load_dirty_baseline_rejects_malformed_payloads,
    test_load_dirty_baseline_returns_none_for_missing_root,
)

__all__ = [
    "BASELINE_FILENAME",
    "FINALIZER_BASELINE_FILENAME",
    "SDD_STORAGE_SIDECAR_REPOS",
    "SIBLING_REPOS_JSON_ENV",
    "SddStore",
    "capture_dirty_baseline",
    "capture_opened_repo_dirty_baseline",
    "collect_dirty_state",
    "dirty_path_fingerprints",
    "finalizer_git",
    "init_git_repo",
    "json",
    "load_dirty_baseline",
    "load_finalizer_baseline_records",
    "Path",
    "protected_baseline_paths",
    "pytest",
    "set_agent_env",
    "set_clean_main",
    "split_pre_existing_changed_files",
    "subprocess",
    "test_baseline_dirty_file_edited_again_stays_in_must_commit_set",
    "test_capture_records_clean_sdd_sidecar_before_late_open",
    "test_capture_records_head_for_run_start_repo",
    "test_capture_writes_fingerprints_for_dirty_paths",
    "test_capture_writes_no_baseline_when_dirty_state_collection_fails",
    "test_clean_baseline_does_not_affect_files_dirtied_after_capture",
    "test_continuation_run_finalizer_commits_inherited_starters_work",
    "test_corrupt_baseline_file_degrades_to_no_baseline",
    "test_finalizer_baseline_views_share_scope_and_duplicate_path_contract",
    "test_historical_opened_repo_baseline_views_agree",
    "test_late_open_baseline_capture_first_path_wins",
    "test_late_open_baseline_capture_first_repo_id_wins",
    "test_legacy_baseline_record_without_head_parses_and_skips_detection",
    "test_load_dirty_baseline_reads_historical_legacy_file_only",
    "test_load_dirty_baseline_rejects_malformed_payloads",
    "test_load_dirty_baseline_returns_none_for_missing_root",
    "test_missing_baseline_file_behaves_like_no_baseline",
    "test_pre_existing_main_file_is_excluded_and_reported_separately",
    "test_pre_existing_sibling_file_is_excluded_and_reported_separately",
    "test_split_pre_existing_changed_files_requires_matching_hash",
]
