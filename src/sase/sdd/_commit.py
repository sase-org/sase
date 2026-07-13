"""Compatibility facade for SDD git commit helpers.

Implementations are split between bounded git execution, storage-repository
commits, and bare-git initialization commits. This module retains the original
import surface for callers and tests.
"""

import subprocess  # Re-exported for compatibility with existing test patches.
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.sdd._commit_bare_git import (
    commit_bare_git_sdd_init_paths,
    ensure_bare_git_sdd_initialized,
    git_toplevel,
    is_local_bare_git_workspace,
    relative_git_pathspecs,
)
from sase.sdd._commit_store import (
    changed_sdd_files,
    commit_sdd_files,
    normalize_sdd_commit_pathspecs,
    push_sdd_store_after_commit,
    sdd_commit_targets,
    sdd_store_label,
)
from sase.sdd._git import (
    DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS,
    DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS,
    DEFAULT_SLOW_GIT_MS,
    ENV_LOCAL_TIMEOUT,
    ENV_NETWORK_TIMEOUT,
    ENV_SLOW_MS,
    SddGitCommandTimeout,
    network_git_timeout,
    run_sdd_git,
)
from sase.sdd._store_types import (
    SDD_STORAGE_SIDECAR_REPOS,
    SDD_STORAGE_SEPARATE_REPO,
)

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


def commit_sdd_store_files(
    store: "SddStore",
    message: str,
    *,
    auto_commit_type: str = "sdd",
    paths: Iterable[str | Path] | None = None,
    push_after_commit: bool | Literal["async"] | None = None,
    artifacts_dir: str | Path | None = None,
) -> bool:
    """Commit SDD files in their owning repository and push per config.

    Push failure never changes the commit result; the local commit is
    preserved and failures are logged.
    """
    committed_any = False
    for target_store, target_paths in sdd_commit_targets(store, paths):
        committed = commit_sdd_files(
            target_store.repo_root,
            message,
            auto_commit_type=auto_commit_type,
            paths=target_paths,
            artifacts_dir=artifacts_dir,
            repo_name=sdd_store_label(target_store),
            record_commit_marker=target_store.storage
            in {SDD_STORAGE_SEPARATE_REPO, SDD_STORAGE_SIDECAR_REPOS},
        )
        if committed:
            push_sdd_store_after_commit(
                target_store, push_after_commit=push_after_commit
            )
            committed_any = True
    return committed_any


__all__ = [
    "SddGitCommandTimeout",
    "changed_sdd_files",
    "commit_bare_git_sdd_init_paths",
    "commit_sdd_files",
    "commit_sdd_store_files",
    "ensure_bare_git_sdd_initialized",
    "git_toplevel",
    "is_local_bare_git_workspace",
    "network_git_timeout",
    "normalize_sdd_commit_pathspecs",
    "relative_git_pathspecs",
    "run_sdd_git",
]
