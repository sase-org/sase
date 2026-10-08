"""Closed/total phase progress for `%wait(for_epic=)` followed epics.

The `[agents]` lane narrates each followed epic as
`↪ <epic> <glyph> <status> · <closed>/<total> phases · since <HH:MM>`.
Row rendering and lane building never touch bead storage, so the counts
are warmed off the event loop by the bead-confirmation warmup and read
here from a small TTL cache. A cold entry renders no count and never
claims the epic is missing.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any, Final

from sase.core.wait_epic_follow_view import epic_follow_views

EpicProgressCacheKey = tuple[str, str]

_CACHE_TTL_SECONDS: Final = 15.0
_CACHE_MISS_TTL_SECONDS: Final = 60.0
_CACHE_MAX_ENTRIES: Final = 256


@dataclass(frozen=True, slots=True)
class _EpicFollowProgress:
    """Memory-only phase progress for one followed epic."""

    closed: int
    total: int
    resolution: str | None = None


class _EpicFollowProgressCache:
    """Small TTL-bounded cache for followed-epic phase progress."""

    def __init__(
        self,
        *,
        ttl_seconds: float = _CACHE_TTL_SECONDS,
        miss_ttl_seconds: float = _CACHE_MISS_TTL_SECONDS,
        max_entries: int,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._miss_ttl_seconds = miss_ttl_seconds
        self._max_entries = max_entries
        self._entries: OrderedDict[
            EpicProgressCacheKey,
            tuple[float, _EpicFollowProgress | None],
        ] = OrderedDict()
        self._lock = RLock()

    def get(self, key: EpicProgressCacheKey) -> _EpicFollowProgress | None | object:
        """Return the cached progress, ``None`` for a known miss, or a miss."""
        from sase.ace.tui.models.agent_wait_beads import (
            WAIT_BEAD_STATUS_CACHE_MISS,
        )

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return WAIT_BEAD_STATUS_CACHE_MISS
            _, value = entry
            self._entries.move_to_end(key)
            return value

    def should_resolve(self, key: EpicProgressCacheKey) -> bool:
        """Return whether *key* has no entry or needs TTL revalidation."""
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return True
            expires_at, _ = entry
            self._entries.move_to_end(key)
            return expires_at <= now

    def set(self, key: EpicProgressCacheKey, value: _EpicFollowProgress | None) -> None:
        """Store *value* (`None` marks a known-unresolvable epic)."""
        ttl_seconds = self._miss_ttl_seconds if value is None else self._ttl_seconds
        expires_at = monotonic() + ttl_seconds
        with self._lock:
            self._entries[key] = (expires_at, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_EPIC_FOLLOW_PROGRESS_CACHE = _EpicFollowProgressCache(max_entries=_CACHE_MAX_ENTRIES)


def _followed_epic_ids(agent: Any) -> tuple[str, ...]:
    """Return the deduplicated epic IDs of FOLLOWING targets this row waits on.

    Only targets still listed in the row's own `waiting_for` contribute,
    mirroring the follow-segment counts. Pure in-memory coercion over the
    already-loaded agent: never touches the filesystem.
    """
    from sase.ace.tui.models.agent_time import wait_display_agent

    wait_agent = wait_display_agent(agent)  # type: ignore[arg-type]
    allowed = set(wait_agent.waiting_for)
    epic_ids: list[str] = []
    for view in epic_follow_views(wait_agent):
        if view.state != "following" or view.target not in allowed:
            continue
        for epic_id in view.epic_ids:
            if epic_id not in epic_ids:
                epic_ids.append(epic_id)
    return tuple(epic_ids)


def _follow_progress_project_key(agent: Any, wait_agent: Any) -> str | None:
    """Return the bead-store project key for a waiter's followed epics."""
    project_file = getattr(wait_agent, "project_file", None) or getattr(
        agent, "project_file", None
    )
    if not project_file:
        return None
    project_key = Path(str(project_file)).parent.name
    return project_key or None


def cached_epic_follow_progress_snapshot(
    agent: Any,
) -> dict[str, _EpicFollowProgress | None]:
    """Return memory-only phase progress for the followed epics of *agent*.

    Missing or expired entries map to `None`: the lane renders no count
    until the warmup resolves them.
    """
    from sase.ace.tui.models.agent_time import wait_display_agent
    from sase.ace.tui.models.agent_wait_beads import (
        WAIT_BEAD_STATUS_CACHE_MISS,
    )

    wait_agent = wait_display_agent(agent)  # type: ignore[arg-type]
    project_key = _follow_progress_project_key(agent, wait_agent)
    snapshot: dict[str, _EpicFollowProgress | None] = {}
    if project_key is None:
        return dict.fromkeys(_followed_epic_ids(agent))
    for epic_id in _followed_epic_ids(agent):
        value = _EPIC_FOLLOW_PROGRESS_CACHE.get((project_key, epic_id))
        if value is WAIT_BEAD_STATUS_CACHE_MISS:
            snapshot[epic_id] = None
        else:
            snapshot[epic_id] = value  # type: ignore[assignment]
    return snapshot


def should_resolve_epic_follow_progress(agent: Any) -> bool:
    """Return whether any followed epic of *agent* needs progress warmup."""
    from sase.ace.tui.models.agent_time import wait_display_agent

    wait_agent = wait_display_agent(agent)  # type: ignore[arg-type]
    project_key = _follow_progress_project_key(agent, wait_agent)
    if project_key is None:
        return False
    return any(
        _EPIC_FOLLOW_PROGRESS_CACHE.should_resolve((project_key, epic_id))
        for epic_id in _followed_epic_ids(agent)
    )


def _read_epic_follow_progress(
    project_key: str,
    epic_ids: Iterable[str],
) -> dict[str, _EpicFollowProgress | None]:
    """Read closed/total phase progress for *epic_ids* from the bead store.

    Must only be called off the Textual event loop. Epics that cannot be
    resolved map to `None` and never fail the warmup.
    """
    from sase.bead.model import Status
    from sase.bead.store_locator import (
        canonical_beads_dir_for_project,
        open_bead_project_for_beads_dir,
    )

    wanted = list(dict.fromkeys(epic_ids))
    try:
        beads_dir = canonical_beads_dir_for_project(project_key)
        if beads_dir is None:
            return dict.fromkeys(wanted)
        with open_bead_project_for_beads_dir(beads_dir) as bead_project:
            resolved: dict[str, _EpicFollowProgress | None] = {}
            for epic_id in wanted:
                try:
                    children = bead_project.get_epic_children(epic_id)
                except Exception:
                    resolved[epic_id] = None
                    continue
                closed = sum(1 for child in children if child.status is Status.CLOSED)
                resolved[epic_id] = _EpicFollowProgress(
                    closed=closed,
                    total=len(children),
                )
            try:
                closed_issues = bead_project.list_issues(statuses=[Status.CLOSED])
            except Exception:
                closed_issues = []
            resolutions = {
                issue.id: (
                    issue.resolution.value if issue.resolution is not None else None
                )
                for issue in closed_issues
            }
            for epic_id, progress in resolved.items():
                if progress is None:
                    continue
                resolution = resolutions.get(epic_id)
                if resolution:
                    resolved[epic_id] = _EpicFollowProgress(
                        closed=progress.closed,
                        total=progress.total,
                        resolution=resolution,
                    )
            return resolved
    except Exception:
        return dict.fromkeys(wanted)


def warm_epic_follow_progress(
    agents: Iterable[Any],
) -> set[Any]:
    """Resolve stale followed-epic progress in project batches.

    Returns identities whose cache-visible projection changed. Store
    lookups happen here, so callers must run this off the Textual event
    loop.
    """
    from sase.ace.tui.models.agent_time import wait_display_agent

    agent_list = list(agents)
    before: dict[Any, tuple[tuple[str, str], ...]] = {}
    for agent in agent_list:
        identity = getattr(agent, "identity", None)
        if identity is None:
            continue
        before[identity] = tuple(
            sorted(
                (epic_id, repr(progress))
                for epic_id, progress in cached_epic_follow_progress_snapshot(
                    agent
                ).items()
            )
        )
    project_epics: dict[str, OrderedDict[str, None]] = {}
    for agent in agent_list:
        wait_agent = wait_display_agent(agent)  # type: ignore[arg-type]
        project_key = _follow_progress_project_key(agent, wait_agent)
        if project_key is None:
            continue
        for epic_id in _followed_epic_ids(agent):
            key = (project_key, epic_id)
            if not _EPIC_FOLLOW_PROGRESS_CACHE.should_resolve(key):
                continue
            project_epics.setdefault(project_key, OrderedDict()).setdefault(
                epic_id,
                None,
            )
    for project_key, epics_by_id in project_epics.items():
        epic_ids = list(epics_by_id)
        resolved = _read_epic_follow_progress(project_key, epic_ids)
        for epic_id in epic_ids:
            _EPIC_FOLLOW_PROGRESS_CACHE.set(
                (project_key, epic_id), resolved.get(epic_id)
            )
    changed: set[Any] = set()
    for agent in agent_list:
        identity = getattr(agent, "identity", None)
        if identity is None:
            continue
        previous = before.get(identity)
        if previous is None:
            continue
        current = tuple(
            sorted(
                (epic_id, repr(progress))
                for epic_id, progress in cached_epic_follow_progress_snapshot(
                    agent
                ).items()
            )
        )
        if current != previous:
            changed.add(identity)
    return changed


__all__ = [
    "EpicProgressCacheKey",
    "cached_epic_follow_progress_snapshot",
    "should_resolve_epic_follow_progress",
    "warm_epic_follow_progress",
]
