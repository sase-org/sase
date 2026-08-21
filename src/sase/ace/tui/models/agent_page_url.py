"""Best-effort hosted page URLs for terminal agent rows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from sase.agent.names.registry_freshness import (
    agent_name_registry_freshness_token,
)
from sase.agent.status_buckets import agent_status_bucket
from sase.sdd.hosted_links import HostedLinkResolver, hosted_link_resolver
from sase.sdd.store import resolve_sdd_store
from sase.workspace_provider.utils import parse_workspace_dir

from .agent import Agent
from ..widgets.prompt_panel._agent_commits import agent_commit_groups


@dataclass(frozen=True, slots=True)
class _RegistrySnapshotKey:
    store_root: str
    project: str
    primary_root: str
    freshness_token: int


@dataclass(frozen=True, slots=True)
class _RegistrySnapshotCacheEntry:
    loaded_at: float


_AGENT_PAGE_REGISTRY_SNAPSHOTS: dict[
    _RegistrySnapshotKey, _RegistrySnapshotCacheEntry
] = {}
_MAX_AGENT_PAGE_REGISTRY_SNAPSHOTS = 32
_AGENT_PAGE_REGISTRY_SNAPSHOT_TTL_SECONDS = 30.0


def _registry_snapshot_now() -> float:
    return time.monotonic()


def agent_publishes_page(agent: Agent) -> bool:
    """Return whether ``agent`` should have a published agents-sidecar page."""
    return bool(
        agent_status_bucket(agent) == "Done"
        and agent_commit_groups(agent)
        and agent.agent_name
        and not agent.is_clan_container
    )


def resolve_agent_page_url(agent: Agent) -> str | None:
    """Resolve ``agent``'s hosted sidecar page without raising."""
    if not agent_publishes_page(agent):
        return None
    agent_name = agent.agent_name
    if not agent.project_file or not agent_name:
        return None

    try:
        project_key = Path(agent.project_file).parent.name
        primary_root = parse_workspace_dir(agent.project_file) or agent.workspace_dir
        if not primary_root:
            return None
        store = resolve_sdd_store(primary_root, 1)
        resolver = hosted_link_resolver(
            store,
            project=project_key,
            primary_root=primary_root,
        )
        _snapshot_agent_name_registry(
            resolver,
            store_root=store.repo_root,
            project=project_key,
            primary_root=primary_root,
        )
        return resolver.agent_url(agent_name)
    except Exception:
        return None


def _snapshot_agent_name_registry(
    resolver: HostedLinkResolver,
    *,
    store_root: Path,
    project: str,
    primary_root: Path | str,
) -> None:
    key = _RegistrySnapshotKey(
        store_root=str(Path(store_root).expanduser().resolve(strict=False)),
        project=project,
        primary_root=str(Path(primary_root).expanduser().resolve(strict=False)),
        freshness_token=agent_name_registry_freshness_token(),
    )
    now = _registry_snapshot_now()
    cached = _AGENT_PAGE_REGISTRY_SNAPSHOTS.get(key)
    if (
        cached is not None
        and now - cached.loaded_at < _AGENT_PAGE_REGISTRY_SNAPSHOT_TTL_SECONDS
    ):
        return
    resolver.snapshot_agent_name_registry()
    _AGENT_PAGE_REGISTRY_SNAPSHOTS[key] = _RegistrySnapshotCacheEntry(loaded_at=now)
    if len(_AGENT_PAGE_REGISTRY_SNAPSHOTS) > _MAX_AGENT_PAGE_REGISTRY_SNAPSHOTS:
        oldest = next(iter(_AGENT_PAGE_REGISTRY_SNAPSHOTS))
        _AGENT_PAGE_REGISTRY_SNAPSHOTS.pop(oldest, None)


__all__ = [
    "agent_publishes_page",
    "resolve_agent_page_url",
]
