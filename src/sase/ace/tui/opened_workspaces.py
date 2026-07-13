"""Loader for per-agent ``sase repo open`` artifact markers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.models.agent import Agent
from sase.linked_repos import (
    OPENED_LINKED_FILENAME,
    OPENED_SIBLINGS_FILENAME,
    opened_linked_repo_records,
)

MAX_KEPT_OPENED_WORKSPACES = 50
_MIN_REREAD_INTERVAL_S = 0.5


@dataclass(frozen=True)
class OpenedWorkspaceDisplayEvent:
    """An opened linked workspace paired with an optional family role label."""

    name: str
    workspace_dir: str
    reason: str
    opened_at: str
    agent_label: str | None = None


@dataclass
class _OpenedWorkspacesCacheEntry:
    events: tuple[OpenedWorkspaceDisplayEvent, ...]
    marker_mtime_ns: tuple[int, ...]
    last_read_monotonic: float


_opened_workspaces_cache: dict[str, _OpenedWorkspacesCacheEntry] = {}
_opened_workspaces_context_cache: dict[
    tuple[str, ...], _OpenedWorkspacesCacheEntry
] = {}


def _stat_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _artifact_root(agent: Agent) -> Path | None:
    artifacts_dir = agent.get_artifacts_dir()
    if not artifacts_dir:
        return None
    return Path(artifacts_dir).expanduser().resolve(strict=False)


def _marker_mtimes(artifact_root: Path | None) -> tuple[int, int]:
    if artifact_root is None:
        return (0, 0)
    return (
        _stat_mtime_ns(artifact_root / OPENED_LINKED_FILENAME),
        _stat_mtime_ns(artifact_root / OPENED_SIBLINGS_FILENAME),
    )


def _event_from_record(
    record: dict[str, str],
    *,
    agent_label: str | None,
) -> OpenedWorkspaceDisplayEvent | None:
    name = record.get("name", "").strip()
    if not name:
        return None
    return OpenedWorkspaceDisplayEvent(
        name=name,
        workspace_dir=record.get("workspace_dir", ""),
        reason=record.get("reason", ""),
        opened_at=record.get("opened_at", ""),
        agent_label=agent_label,
    )


def _sort_events(
    events: list[OpenedWorkspaceDisplayEvent],
) -> tuple[OpenedWorkspaceDisplayEvent, ...]:
    return tuple(
        sorted(
            events,
            key=lambda event: (event.opened_at, event.agent_label or "", event.name),
            reverse=True,
        )
    )


def _load_opened_workspaces_for_agent(
    agent: Agent, *, limit: int = MAX_KEPT_OPENED_WORKSPACES
) -> tuple[OpenedWorkspaceDisplayEvent, ...]:
    """Return linked workspaces opened by ``agent``, newest first.

    Uses an mtime-keyed cache + throttle so repeated detail-panel renders do
    not re-read marker JSON while the user is navigating.
    """

    artifact_root = _artifact_root(agent)
    if artifact_root is None:
        return ()

    now = time.monotonic()
    key = str(artifact_root)
    cached = _opened_workspaces_cache.get(key)
    current_mtime = _marker_mtimes(artifact_root)

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_mtime == cached.marker_mtime_ns:
            return cached.events[:limit]

    events: list[OpenedWorkspaceDisplayEvent] = []
    for record in opened_linked_repo_records(artifact_root).values():
        event = _event_from_record(record, agent_label=None)
        if event is not None:
            events.append(event)

    capped = _sort_events(events)[:MAX_KEPT_OPENED_WORKSPACES]
    _opened_workspaces_cache[key] = _OpenedWorkspacesCacheEntry(
        events=capped,
        marker_mtime_ns=current_mtime,
        last_read_monotonic=now,
    )
    return capped[:limit]


def load_opened_workspaces_for_agent_context(
    agent: Agent, *, limit: int = MAX_KEPT_OPENED_WORKSPACES
) -> tuple[OpenedWorkspaceDisplayEvent, ...]:
    """Return opened linked-workspace events for an agent-family context."""

    from sase.ace.tui.agent_context_members import (
        build_context_members,
        context_cache_key,
    )

    members = build_context_members(agent)
    if len(members) <= 1:
        return _load_opened_workspaces_for_agent(agent, limit=limit)

    now = time.monotonic()
    key = context_cache_key(members)
    cached = _opened_workspaces_context_cache.get(key)
    current_mtime = tuple(
        mtime
        for member in members
        for mtime in _marker_mtimes(
            Path(member.artifacts_dir).expanduser().resolve(strict=False)
            if member.artifacts_dir
            else None
        )
    )

    if cached is not None:
        recent = (now - cached.last_read_monotonic) < _MIN_REREAD_INTERVAL_S
        if recent or current_mtime == cached.marker_mtime_ns:
            return cached.events[:limit]

    events: list[OpenedWorkspaceDisplayEvent] = []
    seen: set[tuple[str, str]] = set()
    for member in members:
        if not member.artifacts_dir:
            continue
        artifact_root = Path(member.artifacts_dir).expanduser().resolve(strict=False)
        for name, record in opened_linked_repo_records(artifact_root).items():
            dedupe_key = (member.cache_key, name)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            event = _event_from_record(record, agent_label=member.label)
            if event is not None:
                events.append(event)

    capped = _sort_events(events)[:MAX_KEPT_OPENED_WORKSPACES]
    _opened_workspaces_context_cache[key] = _OpenedWorkspacesCacheEntry(
        events=capped,
        marker_mtime_ns=current_mtime,
        last_read_monotonic=now,
    )
    return capped[:limit]
