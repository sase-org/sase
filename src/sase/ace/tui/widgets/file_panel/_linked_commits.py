"""Linked-repository commit-message computation for selected agents."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from sase.vcs_provider import VCSProviderNotFoundError

from ...models.agent import Agent, LinkedRepoMetadata
from ._diff import (
    DIFF_CACHE_TTL_SECONDS,
    git_index_signature_for_live_diff,
    resolve_vcs_provider_for_live_diff,
)
from ._linked_deltas import existing_workspace_dir, suffix_workspace_linked_repos

LINKED_COMMITS_REFRESH_INTERVAL_SECONDS = DIFF_CACHE_TTL_SECONDS
_COMMIT_ROW_SEPARATOR = "\x1f"


@dataclass(frozen=True)
class CommitInfo:
    """Compact display data for one commit."""

    short_sha: str
    subject: str


@dataclass(frozen=True)
class LinkedCommitGroup:
    """Commit messages for one linked repository workspace."""

    repo_name: str
    workspace_dir: str
    commits: tuple[CommitInfo, ...]
    fetched_at: datetime | None = None


LinkedCommitCacheKey = tuple[
    tuple[object, ...],  # agent.identity
    str,  # repo name
    str,  # workspace_dir
    str,  # VCS provider name
    tuple[int, int] | None,  # .git/index (mtime_ns, size)
    int,  # TTL bucket
]

_linked_commit_cache: dict[LinkedCommitCacheKey, LinkedCommitGroup | None] = {}
_selected_agent_linked_commit_cache: dict[
    tuple[object, ...],
    tuple[LinkedCommitGroup, ...],
] = {}
_selected_agent_cache_monotonic: dict[tuple[object, ...], float] = {}
_linked_commit_cache_lock = Lock()


def _eligible_linked_repos(agent: Agent) -> tuple[LinkedRepoMetadata, ...]:
    return suffix_workspace_linked_repos(agent)


def should_refresh_linked_commit_groups(agent: Agent) -> bool:
    """Return whether a worker should refresh linked commit data for *agent*.

    This is an in-memory decision so the render path can ask it without
    touching Git or the filesystem.
    """
    if not _eligible_linked_repos(agent):
        return False

    identity = agent.identity
    with _linked_commit_cache_lock:
        last_refresh = _selected_agent_cache_monotonic.get(identity)
    if last_refresh is None:
        return True
    return (time.monotonic() - last_refresh) >= LINKED_COMMITS_REFRESH_INTERVAL_SECONDS


def get_cached_linked_commit_groups(agent: Agent) -> tuple[LinkedCommitGroup, ...]:
    """Return cached linked commit groups for *agent* without doing I/O."""
    if not _eligible_linked_repos(agent):
        return ()
    with _linked_commit_cache_lock:
        return _selected_agent_linked_commit_cache.get(agent.identity, ())


def _cache_key(
    agent: Agent,
    repo_name: str,
    workspace_dir: str,
) -> tuple[LinkedCommitCacheKey, object] | None:
    try:
        provider = resolve_vcs_provider_for_live_diff(workspace_dir)
    except VCSProviderNotFoundError:
        return None
    provider_name = type(provider).__name__
    fingerprint = git_index_signature_for_live_diff(workspace_dir)
    ttl_bucket = int(time.time() // DIFF_CACHE_TTL_SECONDS)
    return (
        (
            agent.identity,
            repo_name,
            workspace_dir,
            provider_name,
            fingerprint,
            ttl_bucket,
        ),
        provider,
    )


def _parse_commit_rows(raw_text: str | None) -> tuple[CommitInfo, ...]:
    if not raw_text:
        return ()

    commits: list[CommitInfo] = []
    for line in raw_text.splitlines():
        row = line.strip()
        if not row:
            continue
        if _COMMIT_ROW_SEPARATOR in row:
            short_sha, subject = row.split(_COMMIT_ROW_SEPARATOR, 1)
        else:
            short_sha, _, subject = row.partition(" ")
        short_sha = short_sha.strip()
        subject = subject.strip()
        if short_sha and subject:
            commits.append(CommitInfo(short_sha=short_sha, subject=subject))
    return tuple(commits)


def _compute_repo_commit_group(
    agent: Agent,
    repo_name: str,
    workspace_dir: str,
) -> LinkedCommitGroup | None:
    keyed_provider = _cache_key(agent, repo_name, workspace_dir)
    if keyed_provider is None:
        return None
    key, provider = keyed_provider

    with _linked_commit_cache_lock:
        if key in _linked_commit_cache:
            return _linked_commit_cache[key]

    try:
        base_ref = provider.get_default_parent_revision(workspace_dir)  # type: ignore[attr-defined]
        ok, raw_commits = provider.list_commits(base_ref, "HEAD", workspace_dir)  # type: ignore[attr-defined]
    except Exception:
        return None
    if not ok:
        return None

    commits = _parse_commit_rows(raw_commits)
    group = (
        LinkedCommitGroup(
            repo_name=repo_name,
            workspace_dir=workspace_dir,
            commits=commits,
            fetched_at=datetime.now(),
        )
        if commits
        else None
    )
    with _linked_commit_cache_lock:
        _linked_commit_cache[key] = group
    return group


def compute_linked_commit_groups(agent: Agent) -> tuple[LinkedCommitGroup, ...]:
    """Compute linked-repo commit groups for *agent*.

    This function may shell out through the VCS provider and must run off the
    Textual event loop.
    """
    groups: list[LinkedCommitGroup] = []
    for repo in _eligible_linked_repos(agent):
        workspace_dir = existing_workspace_dir(repo.workspace_dir)
        if workspace_dir is None:
            continue
        group = _compute_repo_commit_group(agent, repo.name, workspace_dir)
        if group is not None and group.commits:
            groups.append(group)

    result = tuple(groups)
    with _linked_commit_cache_lock:
        _selected_agent_linked_commit_cache[agent.identity] = result
        _selected_agent_cache_monotonic[agent.identity] = time.monotonic()
    return result
