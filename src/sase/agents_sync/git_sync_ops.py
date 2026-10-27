"""Low-level Git and locking operations for agents sidecar synchronization."""

from __future__ import annotations

from sase.agents_sync._git_sync_ops_git import (
    abort_agents_rebase,
    agents_ahead_count,
    agents_git_dir,
    agents_git_error,
    coerce_owner,
    ensure_agents_clone,
    is_agents_non_fast_forward,
    pull_agents_rebase,
)
from sase.agents_sync._git_sync_ops_lock import (
    DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS,
    bounded_agents_lock,
    configured_agents_lock_timeout,
    lock_holder_diagnostic,
)
from sase.agents_sync._git_sync_ops_payload import (
    AGENTS_SYNC_AUTO_COMMIT_TYPE,
    clean_agents_payload_worktree,
    commit_agents_payload_if_dirty,
)

__all__ = [
    "AGENTS_SYNC_AUTO_COMMIT_TYPE",
    "DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS",
    "abort_agents_rebase",
    "agents_ahead_count",
    "agents_git_dir",
    "agents_git_error",
    "bounded_agents_lock",
    "clean_agents_payload_worktree",
    "coerce_owner",
    "commit_agents_payload_if_dirty",
    "configured_agents_lock_timeout",
    "ensure_agents_clone",
    "is_agents_non_fast_forward",
    "lock_holder_diagnostic",
    "pull_agents_rebase",
]
