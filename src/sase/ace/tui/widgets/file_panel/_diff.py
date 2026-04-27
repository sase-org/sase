"""VCS diff fetching for the file panel.

Phase 6 of the TUI perf overhaul adds dedupe + caching at this layer:

- ``compute_diff_cache_key`` derives a stable key from the agent identity,
  workspace path, VCS provider, and a worktree fingerprint (``.git/index``
  mtime/size with a 2-second TTL fallback for active agents).
- A module-level ``_diff_cache`` stores recent results so re-selecting the
  same active agent with an unchanged worktree does not re-call
  ``diff_with_untracked``.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Lock

from sase.running_field import get_workspace_directory
from sase.vcs_provider import VCSProviderNotFoundError, get_vcs_provider

from ...models.agent import Agent

# Worktree TTL fallback: when no .git/index signature is available we still
# want a cache hit for very-recent re-selections of an active agent. Two
# seconds is short enough that fresh edits show up quickly while still
# absorbing rapid j/k bursts on the same agent.
DIFF_CACHE_TTL_SECONDS = 2.0

DiffCacheKey = tuple[
    tuple[object, ...],  # agent.identity
    str,  # workspace_dir
    str,  # vcs provider name
    tuple[int, int] | None,  # .git/index (mtime_ns, size)
    int | None,  # 2-second TTL bucket (used only when index sig missing)
]


_diff_cache: dict[DiffCacheKey, str | None] = {}
_diff_cache_lock = Lock()


def _git_index_signature(workspace_dir: str) -> tuple[int, int] | None:
    git_index = os.path.join(workspace_dir, ".git", "index")
    try:
        st = os.stat(git_index)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _resolve_workspace_dir(agent: Agent) -> str | None:
    project_basename = Path(agent.project_file).stem
    try:
        if agent.workspace_num:
            return get_workspace_directory(project_basename, agent.workspace_num)
        return get_workspace_directory(project_basename, 1)
    except RuntimeError:
        return None


def compute_diff_cache_key(agent: Agent) -> DiffCacheKey | None:
    """Build the diff cache key for an agent, or None if not derivable.

    The 2-second TTL bucket is included only when the workspace has no
    ``.git/index`` (e.g. a non-git VCS or an unborn repo). When ``.git/index``
    is present the (mtime_ns, size) signature is precise so we don't need a
    time-based bucket — the key changes naturally when the index moves.
    """
    workspace_dir = _resolve_workspace_dir(agent)
    if workspace_dir is None:
        return None
    try:
        provider = get_vcs_provider(workspace_dir)
    except VCSProviderNotFoundError:
        return None
    provider_name = type(provider).__name__
    fingerprint = _git_index_signature(workspace_dir)
    ttl_bucket = (
        int(time.time() // DIFF_CACHE_TTL_SECONDS) if fingerprint is None else None
    )
    return (agent.identity, workspace_dir, provider_name, fingerprint, ttl_bucket)


def get_agent_diff(agent: Agent) -> str | None:
    """Get diff output for an agent.

    For completed agents with a diff_path, read the pre-computed diff file.
    For RUNNING agents, use workspace_num to find directory and run live diff,
    caching by ``compute_diff_cache_key``.

    Args:
        agent: The agent to get diff for.

    Returns:
        Diff output string, or None if unavailable.
    """
    # Prefer the pre-computed diff file (e.g. from the gh workflow's diff
    # step).  This is authoritative — the workspace may have been released
    # and reused by the time we display the diff.
    if agent.diff_path:
        try:
            text = Path(agent.diff_path).read_text()
            return text if text.strip() else None
        except OSError:
            pass

    # For completed agents, the diff_path is the only reliable source.
    # The workspace may have been released and reused by another agent,
    # so falling back to `git diff HEAD~1..HEAD` would show an unrelated
    # commit's diff.
    if agent.status in ("DONE", "FAILED"):
        return None

    try:
        project_basename = Path(agent.project_file).stem
        if agent.workspace_num:
            workspace_dir = get_workspace_directory(
                project_basename, agent.workspace_num
            )
        else:
            workspace_dir = get_workspace_directory(project_basename, 1)

        try:
            provider = get_vcs_provider(workspace_dir)
        except VCSProviderNotFoundError:
            return None

        provider_name = type(provider).__name__
        fingerprint = _git_index_signature(workspace_dir)
        ttl_bucket = (
            int(time.time() // DIFF_CACHE_TTL_SECONDS) if fingerprint is None else None
        )
        key: DiffCacheKey = (
            agent.identity,
            workspace_dir,
            provider_name,
            fingerprint,
            ttl_bucket,
        )

        with _diff_cache_lock:
            if key in _diff_cache:
                return _diff_cache[key]

        _, diff_text = provider.diff_with_untracked(workspace_dir, timeout=10)
        result = diff_text if diff_text else None

        with _diff_cache_lock:
            _diff_cache[key] = result
        return result

    except RuntimeError:
        return None
    except Exception:
        return None
