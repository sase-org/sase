"""Shared helpers for Git index-lock recovery tests."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


def age_git_index_lock(lock: Path, *, seconds: float = 60.0) -> Path:
    """Stamp *lock* as *seconds* old without waiting on the wall clock."""
    old = time.time() - seconds
    os.utime(lock, (old, old))
    return lock


def absent_owner_facts(
    *,
    lock_path: Path | None = None,
    resolved_git_dir: str | None = None,
    resolved_worktree: str | None = None,
    timeout: float = 1.0,
) -> dict[str, Any]:
    """Return complete owner-probe facts with no associated processes."""
    del timeout
    return {
        "schema_version": 1,
        "probe_status": "complete",
        "probe_reason": "test fixture",
        "processes": [],
        "resolved_git_dir": resolved_git_dir,
        "resolved_index_lock_path": None if lock_path is None else str(lock_path),
        "resolved_worktree": resolved_worktree,
    }


def active_owner_facts(
    *,
    lock_path: Path | None = None,
    resolved_git_dir: str | None = None,
    resolved_worktree: str | None = None,
    timeout: float = 1.0,
) -> dict[str, Any]:
    """Return owner-probe facts for a process holding the lock descriptor."""
    del timeout
    return {
        "schema_version": 1,
        "probe_status": "complete",
        "probe_reason": "test fixture",
        "processes": [
            {
                "pid": 4242,
                "ppid": 1,
                "executable": "/usr/bin/git",
                "argv": ["git", "merge"],
                "cwd": resolved_worktree,
                "git_dir_env": resolved_git_dir,
                "git_index_file_env": None,
                "git_work_tree_env": resolved_worktree,
                "holds_lock_descriptor": True,
                "association_ambiguous": False,
            }
        ],
        "resolved_git_dir": resolved_git_dir,
        "resolved_index_lock_path": None if lock_path is None else str(lock_path),
        "resolved_worktree": resolved_worktree,
    }


def incomplete_owner_facts(
    *,
    lock_path: Path | None = None,
    resolved_git_dir: str | None = None,
    resolved_worktree: str | None = None,
    timeout: float = 1.0,
) -> dict[str, Any]:
    """Return incomplete owner-probe facts that must classify as unknown."""
    del timeout
    return {
        "schema_version": 1,
        "probe_status": "incomplete",
        "probe_reason": "missing platform tools",
        "processes": [],
        "resolved_git_dir": resolved_git_dir,
        "resolved_index_lock_path": None if lock_path is None else str(lock_path),
        "resolved_worktree": resolved_worktree,
    }
