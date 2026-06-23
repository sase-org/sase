"""Linked-repository DELTAS computation for active agents."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from sase.agent.status_buckets import status_bucket_for_values
from sase.ace.changespec.models import DeltaEntry
from sase.vcs_provider import VCSProviderNotFoundError

from ...models.agent import Agent, LinkedRepoMetadata
from ._diff import (
    DIFF_CACHE_TTL_SECONDS,
    git_index_signature_for_live_diff,
    resolve_vcs_provider_for_live_diff,
)

LINKED_DELTAS_REFRESH_INTERVAL_SECONDS = DIFF_CACHE_TTL_SECONDS


@dataclass(frozen=True)
class LinkedDeltaGroup:
    """Delta entries for one linked repository workspace."""

    repo_name: str
    workspace_dir: str
    entries: tuple[DeltaEntry, ...]
    diff_text: str = ""
    fetched_at: datetime | None = None


LinkedDeltaCacheKey = tuple[
    tuple[object, ...],  # agent.identity
    str,  # repo name
    str,  # workspace_dir
    str,  # VCS provider name
    tuple[int, int] | None,  # .git/index (mtime_ns, size)
    int,  # TTL bucket
]

_linked_delta_cache: dict[LinkedDeltaCacheKey, LinkedDeltaGroup | None] = {}
_selected_agent_linked_delta_cache: dict[
    tuple[object, ...],
    tuple[LinkedDeltaGroup, ...],
] = {}
_selected_agent_cache_monotonic: dict[tuple[object, ...], float] = {}
_linked_delta_cache_lock = Lock()


def _status_allows_linked_deltas(status: str | None) -> bool:
    return status_bucket_for_values(status) not in {"Done", "Failed"}


def _existing_workspace_dir(workspace_dir: str) -> str | None:
    expanded = os.path.expanduser(workspace_dir)
    if not os.path.isdir(expanded):
        return None
    return os.path.normpath(expanded)


def _eligible_linked_repos(agent: Agent) -> tuple[LinkedRepoMetadata, ...]:
    if not _status_allows_linked_deltas(agent.status):
        return ()

    repos: list[LinkedRepoMetadata] = []
    seen_names: set[str] = set()
    for repo in agent.linked_repos:
        if repo.name in seen_names:
            continue
        seen_names.add(repo.name)
        if repo.workspace_strategy != "suffix":
            continue
        if not repo.workspace_dir:
            continue
        repos.append(repo)
    return tuple(repos)


def should_refresh_linked_delta_groups(agent: Agent) -> bool:
    """Return whether a worker should refresh linked delta data for *agent*.

    This is intentionally an in-memory decision so the render path can ask it
    without touching Git or the filesystem.
    """
    if not _eligible_linked_repos(agent):
        return False

    identity = agent.identity
    with _linked_delta_cache_lock:
        last_refresh = _selected_agent_cache_monotonic.get(identity)
    if last_refresh is None:
        return True
    return (time.monotonic() - last_refresh) >= LINKED_DELTAS_REFRESH_INTERVAL_SECONDS


def get_cached_linked_delta_groups(agent: Agent) -> tuple[LinkedDeltaGroup, ...]:
    """Return cached linked delta groups for *agent* without doing I/O."""
    if not _eligible_linked_repos(agent):
        return ()
    with _linked_delta_cache_lock:
        return _selected_agent_linked_delta_cache.get(agent.identity, ())


def _cache_key(
    agent: Agent,
    repo_name: str,
    workspace_dir: str,
) -> tuple[LinkedDeltaCacheKey, object] | None:
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


def _compute_repo_group(
    agent: Agent,
    repo_name: str,
    workspace_dir: str,
) -> LinkedDeltaGroup | None:
    keyed_provider = _cache_key(agent, repo_name, workspace_dir)
    if keyed_provider is None:
        return None
    key, provider = keyed_provider

    with _linked_delta_cache_lock:
        if key in _linked_delta_cache:
            return _linked_delta_cache[key]

    try:
        has_changes_ok, changes = provider.has_local_changes(workspace_dir)  # type: ignore[attr-defined]
    except Exception:
        return None
    if not has_changes_ok or not changes:
        with _linked_delta_cache_lock:
            _linked_delta_cache[key] = None
        return None

    try:
        _, diff_text = provider.diff_with_untracked(workspace_dir, timeout=10)  # type: ignore[attr-defined]
    except Exception:
        return None
    if not diff_text:
        with _linked_delta_cache_lock:
            _linked_delta_cache[key] = None
        return None

    from ..prompt_panel._agent_deltas import parse_unified_diff_deltas

    entries = tuple(parse_unified_diff_deltas(diff_text))
    group = (
        LinkedDeltaGroup(
            repo_name=repo_name,
            workspace_dir=workspace_dir,
            entries=entries,
            diff_text=diff_text,
            fetched_at=datetime.now(),
        )
        if entries
        else None
    )
    with _linked_delta_cache_lock:
        _linked_delta_cache[key] = group
    return group


def compute_linked_delta_groups(agent: Agent) -> tuple[LinkedDeltaGroup, ...]:
    """Compute linked-repo delta groups for *agent*.

    This function may shell out through the VCS provider and must run off the
    Textual event loop.
    """
    groups: list[LinkedDeltaGroup] = []
    for repo in _eligible_linked_repos(agent):
        workspace_dir = _existing_workspace_dir(repo.workspace_dir)
        if workspace_dir is None:
            continue
        group = _compute_repo_group(agent, repo.name, workspace_dir)
        if group is not None and group.entries:
            groups.append(group)

    result = tuple(groups)
    with _linked_delta_cache_lock:
        _selected_agent_linked_delta_cache[agent.identity] = result
        _selected_agent_cache_monotonic[agent.identity] = time.monotonic()
    return result
