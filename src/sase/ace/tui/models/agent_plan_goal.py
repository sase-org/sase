"""Best-effort plan-goal resolution for Agents-tab detail enrichment."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import os
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Final

from sase.agent.bead_display import (
    BeadIssueLookupSession,
    derive_agent_bead_id_from_name,
    lookup_bead_issue,
)
from sase.bead.model import Issue
from sase.sdd.plan_tiers import read_plan_goal

from .agent import Agent

_CACHE_MAX_ENTRIES = 256
_ASSOCIATION_TTL_SECONDS = 60.0
_NEGATIVE_TTL_SECONDS = 5.0
_CACHE_MISS: Final = object()

PlanAssociationCacheKey = tuple[str, str, str | None, str | None, int]
PlanFileSignature = tuple[int, int]


@dataclass(frozen=True)
class _PlanGoalCacheEntry:
    signature: PlanFileSignature | None
    goal: str | None
    expires_at: float | None = None


class _PlanGoalCache:
    """Bounded goal cache invalidated by the plan file's mtime and size."""

    def __init__(self, *, max_entries: int = _CACHE_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[Path, _PlanGoalCacheEntry] = OrderedDict()
        self._lock = RLock()

    def get(self, path: Path) -> str | None:
        normalized = path.expanduser().resolve(strict=False)
        now = monotonic()
        with self._lock:
            try:
                stat = normalized.stat()
                signature: PlanFileSignature | None = (
                    stat.st_mtime_ns,
                    stat.st_size,
                )
            except OSError:
                signature = None

            entry = self._entries.get(normalized)
            if entry is not None:
                self._entries.move_to_end(normalized)
                if signature is not None and entry.signature == signature:
                    return entry.goal
                if (
                    signature is None
                    and entry.signature is None
                    and entry.expires_at is not None
                    and entry.expires_at > now
                ):
                    return None

            if signature is None:
                result = _PlanGoalCacheEntry(
                    signature=None,
                    goal=None,
                    expires_at=now + _NEGATIVE_TTL_SECONDS,
                )
            else:
                result = _PlanGoalCacheEntry(
                    signature=signature,
                    goal=read_plan_goal(normalized),
                )
            self._entries[normalized] = result
            self._entries.move_to_end(normalized)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return result.goal

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class _PlanAssociationCache:
    """Short-lived cache for direct and bead-derived plan-file resolution."""

    def __init__(self, *, max_entries: int = _CACHE_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[
            PlanAssociationCacheKey, tuple[float, Path | None]
        ] = OrderedDict()
        self._lock = RLock()

    def get(self, key: PlanAssociationCacheKey) -> Path | None | object:
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return _CACHE_MISS
            expires_at, path = entry
            if expires_at <= now:
                del self._entries[key]
                return _CACHE_MISS
            self._entries.move_to_end(key)
            return path

    def set(self, key: PlanAssociationCacheKey, path: Path | None) -> None:
        ttl = _NEGATIVE_TTL_SECONDS if path is None else _ASSOCIATION_TTL_SECONDS
        with self._lock:
            self._entries[key] = (monotonic() + ttl, path)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_PLAN_GOAL_CACHE = _PlanGoalCache()
_PLAN_ASSOCIATION_CACHE = _PlanAssociationCache()


def resolve_agent_plan_goal(
    agent: Agent,
    *,
    lookup_session: BeadIssueLookupSession | None = None,
) -> str | None:
    """Return the selected agent's associated plan goal, if one is readable.

    Resolution may read plan and bead storage, so callers must run it outside
    the Textual event loop. Direct agent metadata is authoritative; bead
    association is consulted only when no direct plan path exists.
    """
    if agent.plan_path:
        key = _association_key(agent, "direct", agent.plan_path)
        plan_path = _PLAN_ASSOCIATION_CACHE.get(key)
        if plan_path is _CACHE_MISS:
            plan_path = _resolve_plan_reference(agent.plan_path, agent)
            _PLAN_ASSOCIATION_CACHE.set(key, plan_path)
        if not isinstance(plan_path, Path):
            return None
        return _PLAN_GOAL_CACHE.get(plan_path)

    bead_id = _agent_bead_id(agent)
    if bead_id is None:
        return None

    key = _association_key(agent, "bead", bead_id)
    plan_path = _PLAN_ASSOCIATION_CACHE.get(key)
    if plan_path is _CACHE_MISS:
        if lookup_session is None:
            with BeadIssueLookupSession() as owned_session:
                plan_path = _resolve_bead_plan_path(
                    agent,
                    bead_id,
                    lookup_session=owned_session,
                )
        else:
            plan_path = _resolve_bead_plan_path(
                agent,
                bead_id,
                lookup_session=lookup_session,
            )
        _PLAN_ASSOCIATION_CACHE.set(key, plan_path)
    if not isinstance(plan_path, Path):
        return None
    return _PLAN_GOAL_CACHE.get(plan_path)


def _resolve_bead_plan_path(
    agent: Agent,
    bead_id: str,
    *,
    lookup_session: BeadIssueLookupSession,
) -> Path | None:
    issue = _lookup_issue(agent, bead_id, lookup_session=lookup_session)
    if issue is None:
        return None
    design = issue.design.strip()
    if not design and issue.parent_id:
        parent = _lookup_issue(
            agent,
            issue.parent_id,
            lookup_session=lookup_session,
        )
        if parent is not None:
            design = parent.design.strip()
    if not design:
        return None
    return _resolve_plan_reference(design, agent)


def _lookup_issue(
    agent: Agent,
    bead_id: str,
    *,
    lookup_session: BeadIssueLookupSession,
) -> Issue | None:
    return lookup_bead_issue(
        bead_id,
        project_name=_agent_project_name(agent),
        workspace_dir=agent.workspace_dir,
        local_only=True,
        lookup_session=lookup_session,
    )


def _agent_bead_id(agent: Agent) -> str | None:
    return (
        agent.phase_bead_id
        or agent.epic_bead_id
        or derive_agent_bead_id_from_name(agent.agent_name)
    )


def _association_key(
    agent: Agent,
    source: str,
    value: str,
) -> PlanAssociationCacheKey:
    workspace_dir = _normalized_workspace_dir(agent.workspace_dir)
    return (
        source,
        value,
        _agent_project_name(agent),
        workspace_dir,
        agent.effective_workspace_num or 1,
    )


def _resolve_plan_reference(reference: str, agent: Agent) -> Path | None:
    raw_path = Path(reference).expanduser()
    if raw_path.is_absolute():
        return _readable_plan_path(raw_path)

    workspace_dir = _agent_workspace_dir(agent)
    workspace_num = agent.effective_workspace_num or 1
    candidates: list[Path] = []
    if workspace_dir is not None:
        candidates.append(workspace_dir / raw_path)
        primary = _primary_workspace_dir(workspace_dir, workspace_num)
        if primary is not None:
            candidates.append(primary / raw_path)
        candidates.extend(_sdd_plan_candidates(workspace_dir, workspace_num, raw_path))

    for candidate in _dedupe_paths(candidates):
        readable = _readable_plan_path(candidate)
        if readable is not None:
            return readable
    return None


def _agent_workspace_dir(agent: Agent) -> Path | None:
    if agent.workspace_dir:
        return Path(agent.workspace_dir).expanduser().resolve(strict=False)
    if not agent.project_file:
        return None
    try:
        from sase.workspace_provider.utils import parse_workspace_dir

        workspace_dir = parse_workspace_dir(agent.project_file)
    except Exception:
        return None
    if not workspace_dir:
        return None
    return Path(workspace_dir).expanduser().resolve(strict=False)


def _primary_workspace_dir(workspace_dir: Path, workspace_num: int) -> Path | None:
    try:
        from sase.sdd._paths import get_primary_workspace_dir

        primary = get_primary_workspace_dir(str(workspace_dir), workspace_num)
    except Exception:
        return None
    return Path(primary).expanduser().resolve(strict=False) if primary else None


def _sdd_plan_candidates(
    workspace_dir: Path,
    workspace_num: int,
    reference: Path,
) -> list[Path]:
    try:
        from sase.sdd.store import resolve_sdd_store

        plan_root = resolve_sdd_store(workspace_dir, workspace_num).kind_root("plans")
    except Exception:
        return []

    parts = reference.parts
    relative = reference
    for prefix in (
        (".sase", "sdd", "plans"),
        ("sdd", "plans"),
        ("plans",),
    ):
        if parts[: len(prefix)] == prefix:
            relative = Path(*parts[len(prefix) :])
            break
    return [plan_root / relative]


def _readable_plan_path(path: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=False)
        return resolved if resolved.is_file() and os.access(resolved, os.R_OK) else None
    except OSError:
        return None


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        normalized = path.expanduser().resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _agent_project_name(agent: Agent) -> str | None:
    if not agent.project_file:
        return None
    return Path(agent.project_file).parent.name or None


def _normalized_workspace_dir(workspace_dir: str | None) -> str | None:
    if not workspace_dir:
        return None
    return os.path.normpath(os.path.expanduser(workspace_dir))
