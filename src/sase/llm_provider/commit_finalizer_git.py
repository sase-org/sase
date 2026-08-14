"""Git and artifact path helpers for commit finalization.

This module is the aggregate entry point for the commit finalizer's git
layer. The implementation lives in four focused siblings:

- ``commit_finalizer_git_paths`` -- path classification and normalization
- ``commit_finalizer_git_status`` -- git subprocess and status queries
- ``commit_finalizer_git_progress`` -- progress and discarded-work detection
- ``commit_finalizer_git_autocommit`` -- narrow SDD auto-commits
"""

from __future__ import annotations

from .commit_finalizer_git_autocommit import (
    auto_commit_done_sdd_plan_status,
    auto_commit_sdd_prompt_qa_candidate,
    sdd_prompt_qa_auto_commit_candidates,
)
from .commit_finalizer_git_paths import (
    filter_sase_reserved_paths,
    is_prompt_archive_path,
    normalize_path,
)
from .commit_finalizer_git_progress import (
    discarded_dirty_work_evidence,
    discarded_dirty_work_message,
    progress_fingerprint,
)
from .commit_finalizer_git_status import (
    changed_files_from_git_status,
    dirty_path_fingerprints,
    git_changed_files,
    split_pre_existing_changed_files,
)

__all__ = [
    "auto_commit_done_sdd_plan_status",
    "auto_commit_sdd_prompt_qa_candidate",
    "changed_files_from_git_status",
    "dirty_path_fingerprints",
    "discarded_dirty_work_evidence",
    "discarded_dirty_work_message",
    "filter_sase_reserved_paths",
    "git_changed_files",
    "is_prompt_archive_path",
    "normalize_path",
    "progress_fingerprint",
    "sdd_prompt_qa_auto_commit_candidates",
    "split_pre_existing_changed_files",
]
