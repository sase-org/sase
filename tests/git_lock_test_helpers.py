"""Shared helpers for Git index-lock recovery tests."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from sase.git_lock_retry import run_with_git_lock_retry


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
    reason: str = "missing platform tools",
) -> dict[str, Any]:
    """Return incomplete owner-probe facts that must classify as unknown."""
    del timeout
    return {
        "schema_version": 1,
        "probe_status": "incomplete",
        "probe_reason": reason,
        "processes": [],
        "resolved_git_dir": resolved_git_dir,
        "resolved_index_lock_path": None if lock_path is None else str(lock_path),
        "resolved_worktree": resolved_worktree,
    }


def patch_git_lock_owner_probe(
    monkeypatch: pytest.MonkeyPatch,
    caller_module: str,
    repo_root: Path,
    owner_probe: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inject deterministic owner facts at a caller's imported executor seam.

    The public retry executor, its Git attempt, and Rust policy classification all
    remain real. Returned observations record that the injected probe ran and
    reject any lock or context path outside the caller's temporary repository.
    """
    root = repo_root.resolve()
    observations: list[dict[str, Any]] = []

    def checked_probe(**kwargs: Any) -> dict[str, Any]:
        observation = dict(kwargs)
        for key in ("lock_path", "resolved_git_dir", "resolved_worktree"):
            value = observation.get(key)
            if value is None:
                continue
            path = Path(value).resolve()
            assert path == root or root in path.parents, (
                f"{key} escaped temporary repository {root}: {path}"
            )
        facts = owner_probe(**kwargs)
        observation["facts"] = facts
        observations.append(observation)
        return facts

    def forwarding_executor(*args: Any, **kwargs: Any) -> Any:
        kwargs["owner_probe"] = checked_probe
        return run_with_git_lock_retry(*args, **kwargs)

    module = import_module(caller_module)
    monkeypatch.setattr(module, "run_with_git_lock_retry", forwarding_executor)
    return observations
