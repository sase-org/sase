"""Linked-repository DELTAS computation for active agents."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import NamedTuple

from sase.agent.status_buckets import status_bucket_for_values
from sase.ace.changespec.models import DeltaEntry
from sase.vcs_provider import VCSProviderNotFoundError

from ...models.agent import Agent, LinkedRepoMetadata
from ._diff import (
    DIFF_CACHE_TTL_SECONDS,
    git_index_signature_for_live_diff,
    resolve_agent_diff_source,
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

_linked_diff_text_cache: dict[LinkedDeltaCacheKey, str | None] = {}
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


def _normalized_workspace_dir(workspace_dir: str) -> str | None:
    if not workspace_dir.strip():
        return None
    return os.path.normpath(os.path.expanduser(workspace_dir))


class _LinkedWorkspaceCandidate(NamedTuple):
    repo_name: str
    workspace_dir: str


def _linked_metadata_agents(agent: Agent) -> tuple[Agent, ...]:
    source = resolve_agent_diff_source(agent)
    if source is agent:
        return (agent,)
    return (agent, source)


def _workspace_linked_repos(agent: Agent) -> tuple[LinkedRepoMetadata, ...]:
    repos: list[LinkedRepoMetadata] = []
    seen: set[tuple[str, str]] = set()
    for metadata_agent in _linked_metadata_agents(agent):
        for repo in metadata_agent.linked_repos:
            workspace_dir = _normalized_workspace_dir(repo.workspace_dir)
            if workspace_dir is None:
                continue
            key = (repo.name, workspace_dir)
            if key in seen:
                continue
            seen.add(key)
            repos.append(
                LinkedRepoMetadata(
                    name=repo.name,
                    workspace_dir=workspace_dir,
                )
            )
    return tuple(repos)


def _has_possible_opened_workspace_markers(agent: Agent) -> bool:
    if agent.artifacts_dir:
        return True
    return any(bool(child.artifacts_dir) for child in agent.followup_agents)


def _eligible_static_linked_repos(agent: Agent) -> tuple[LinkedRepoMetadata, ...]:
    if not _status_allows_linked_deltas(resolve_agent_diff_source(agent).status):
        return ()
    return _workspace_linked_repos(agent)


def _eligible_linked_workspace_candidates(
    agent: Agent,
) -> tuple[_LinkedWorkspaceCandidate, ...]:
    if not _status_allows_linked_deltas(resolve_agent_diff_source(agent).status):
        return ()

    candidates: list[_LinkedWorkspaceCandidate] = []
    seen: set[tuple[str, str]] = set()

    def add(repo_name: str, workspace_dir: str) -> None:
        normalized = _normalized_workspace_dir(workspace_dir)
        if normalized is None:
            return
        key = (repo_name, normalized)
        if key in seen:
            return
        seen.add(key)
        candidates.append(_LinkedWorkspaceCandidate(repo_name, normalized))

    for repo in _workspace_linked_repos(agent):
        add(repo.name, repo.workspace_dir)

    from sase.linked_repos import sidecar_repo_clone_dir

    for metadata_agent in _linked_metadata_agents(agent):
        if not metadata_agent.workspace_dir:
            continue
        for kind in ("plans", "research"):
            workspace_dir = sidecar_repo_clone_dir(
                metadata_agent.workspace_dir,
                kind,
            )
            if os.path.isdir(workspace_dir) and os.path.exists(
                os.path.join(workspace_dir, ".git")
            ):
                add(kind, workspace_dir)

    try:
        from sase.ace.tui.opened_workspaces import (
            load_opened_workspaces_for_agent_context,
        )

        opened_events = load_opened_workspaces_for_agent_context(agent)
    except Exception:
        opened_events = ()

    for event in opened_events:
        add(event.name, event.workspace_dir)

    return tuple(candidates)


def should_refresh_linked_delta_groups(agent: Agent) -> bool:
    """Return whether a worker should refresh linked delta data for *agent*.

    This is intentionally an in-memory decision so the render path can ask it
    without touching Git or the filesystem.
    """
    if not _status_allows_linked_deltas(resolve_agent_diff_source(agent).status):
        return False
    has_workspace = any(
        bool(metadata_agent.workspace_dir)
        for metadata_agent in _linked_metadata_agents(agent)
    )
    if (
        not _eligible_static_linked_repos(agent)
        and not _has_possible_opened_workspace_markers(agent)
        and not has_workspace
    ):
        return False

    identity = agent.identity
    with _linked_delta_cache_lock:
        last_refresh = _selected_agent_cache_monotonic.get(identity)
    if last_refresh is None:
        return True
    return (time.monotonic() - last_refresh) >= LINKED_DELTAS_REFRESH_INTERVAL_SECONDS


def get_cached_linked_delta_groups(agent: Agent) -> tuple[LinkedDeltaGroup, ...]:
    """Return cached linked delta groups for *agent* without doing I/O."""
    if not _status_allows_linked_deltas(resolve_agent_diff_source(agent).status):
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

    diff_text = _fetch_repo_diff_text(key, provider, workspace_dir)
    if not diff_text:
        with _linked_delta_cache_lock:
            _linked_delta_cache[key] = None
        return None

    from ..prompt_panel._agent_deltas import (
        parse_unified_diff_deltas,
        visible_agent_delta_entries,
    )

    entries = tuple(visible_agent_delta_entries(parse_unified_diff_deltas(diff_text)))
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


def _fetch_repo_diff_text(
    key: LinkedDeltaCacheKey,
    provider: object,
    workspace_dir: str,
) -> str | None:
    with _linked_delta_cache_lock:
        if key in _linked_diff_text_cache:
            return _linked_diff_text_cache[key]

    try:
        has_changes_ok, changes = provider.has_local_changes(workspace_dir)  # type: ignore[attr-defined]
    except Exception:
        return None
    if not has_changes_ok or not changes:
        with _linked_delta_cache_lock:
            _linked_diff_text_cache[key] = None
        return None

    try:
        _, diff_text = provider.diff_with_untracked(workspace_dir, timeout=10)  # type: ignore[attr-defined]
    except Exception:
        return None
    if not diff_text:
        with _linked_delta_cache_lock:
            _linked_diff_text_cache[key] = None
        return None

    with _linked_delta_cache_lock:
        _linked_diff_text_cache[key] = diff_text
    return diff_text


def linked_agent_file_change_hint(agent: Agent) -> bool | None:
    """Return whether live linked workspaces have real edits for *agent*."""
    candidates = _eligible_linked_workspace_candidates(agent)
    if not candidates:
        return None

    from ...models._diff_badge import diff_text_has_real_edits

    saw_probe = False
    for candidate in candidates:
        workspace_dir = _existing_workspace_dir(candidate.workspace_dir)
        if workspace_dir is None:
            continue
        keyed_provider = _cache_key(agent, candidate.repo_name, workspace_dir)
        if keyed_provider is None:
            continue
        key, provider = keyed_provider
        diff_text = _fetch_repo_diff_text(key, provider, workspace_dir)
        saw_probe = True
        if diff_text and diff_text_has_real_edits(diff_text):
            return True
    return False if saw_probe or candidates else None


def compute_linked_delta_groups(agent: Agent) -> tuple[LinkedDeltaGroup, ...]:
    """Compute linked-repo delta groups for *agent*.

    This function may shell out through the VCS provider and must run off the
    Textual event loop.
    """
    groups: list[LinkedDeltaGroup] = []
    for candidate in _eligible_linked_workspace_candidates(agent):
        workspace_dir = _existing_workspace_dir(candidate.workspace_dir)
        if workspace_dir is None:
            continue
        group = _compute_repo_group(agent, candidate.repo_name, workspace_dir)
        if group is not None and group.entries:
            groups.append(group)

    result = tuple(groups)
    with _linked_delta_cache_lock:
        _selected_agent_linked_delta_cache[agent.identity] = result
        _selected_agent_cache_monotonic[agent.identity] = time.monotonic()
    return result
