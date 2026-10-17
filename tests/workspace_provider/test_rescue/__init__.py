"""Real-git unit tests for the durable rescue store.

Split from a single module into focused modules; this package preserves the
original ``tests.workspace_provider.test_rescue`` import path and re-exports
every public test for backward compatibility.
"""

from __future__ import annotations

from tests.workspace_provider.test_rescue.test_bundles import (
    test_rescue_bundles_everything_without_remote_tracking_refs,
    test_rescue_bundles_local_commits_restorable_by_fetch,
    test_rescue_includes_every_stash_entry,
)
from tests.workspace_provider.test_rescue.test_store import (
    test_quarantine_directory_moves_clone_outside_workspace,
    test_reap_deletes_only_aged_entries,
    test_rescue_returns_none_when_nothing_to_rescue,
)
from tests.workspace_provider.test_rescue.test_tags import (
    test_rescue_bundle_omits_upstream_off_branch_tags_when_rescuing_branch_work,
    test_rescue_bundles_local_tags_but_not_published_ones,
    test_rescue_bundles_new_commit_on_detached_upstream_tag,
    test_rescue_ignores_annotated_tags_already_on_remote,
    test_rescue_ignores_detached_checkout_of_upstream_tag,
    test_rescue_ignores_upstream_tags_off_every_remote_branch,
)
from tests.workspace_provider.test_rescue.test_worktree import (
    test_rescue_patch_cap_is_honored,
    test_rescue_patch_captures_conflicted_worktree,
    test_rescue_patch_captures_staged_unstaged_and_untracked,
    test_worktree_only_rescue_writes_no_tag_bundle,
)

__all__ = [
    "test_quarantine_directory_moves_clone_outside_workspace",
    "test_reap_deletes_only_aged_entries",
    "test_rescue_bundle_omits_upstream_off_branch_tags_when_rescuing_branch_work",
    "test_rescue_bundles_everything_without_remote_tracking_refs",
    "test_rescue_bundles_local_commits_restorable_by_fetch",
    "test_rescue_bundles_local_tags_but_not_published_ones",
    "test_rescue_bundles_new_commit_on_detached_upstream_tag",
    "test_rescue_ignores_annotated_tags_already_on_remote",
    "test_rescue_ignores_detached_checkout_of_upstream_tag",
    "test_rescue_ignores_upstream_tags_off_every_remote_branch",
    "test_rescue_includes_every_stash_entry",
    "test_rescue_patch_cap_is_honored",
    "test_rescue_patch_captures_conflicted_worktree",
    "test_rescue_patch_captures_staged_unstaged_and_untracked",
    "test_rescue_returns_none_when_nothing_to_rescue",
    "test_worktree_only_rescue_writes_no_tag_bundle",
]
