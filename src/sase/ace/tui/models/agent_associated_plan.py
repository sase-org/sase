"""Associated-plan resolution for deferred Agents-tab detail enrichment."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import os
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Final, Literal

from sase.agent.bead_display import (
    BeadIssueLookupSession,
    derive_agent_bead_id_from_name,
    lookup_bead_issue,
)
from sase.bead.model import Issue
from sase.core.agent_artifact_helpers import select_canonical_plan_path
from sase.core.paths import shorten_path
from sase.sdd.plan_tiers import normalize_plan_tier, read_plan_frontmatter

from .agent import Agent

_CACHE_MAX_ENTRIES = 256
_ASSOCIATION_TTL_SECONDS = 60.0
_NEGATIVE_TTL_SECONDS = 5.0
_CACHE_MISS: Final = object()

AssociatedPlanTier = Literal["plan", "epic", "none"]
AuthoredPlanTier = Literal["tale", "epic"]
PlanAssociationCacheKey = tuple[str, str, str | None, str | None, int]
PlanFileSignature = tuple[int, int]


@dataclass(frozen=True, slots=True)
class AssociatedPlanSummary:
    """Immutable plan metadata consumed by the in-memory render path."""

    goal: str | None
    authored_tier: AuthoredPlanTier | None
    effective_tier: AssociatedPlanTier | None
    actual_path: str
    display_path: str
    committed: bool | None
    exists: bool
    readable: bool
    frontmatter_readable: bool


@dataclass(frozen=True, slots=True)
class _PlanFileMetadata:
    goal: str | None
    authored_tier: AuthoredPlanTier | None
    exists: bool
    readable: bool
    frontmatter_readable: bool


@dataclass(frozen=True, slots=True)
class _PlanFileCacheEntry:
    signature: PlanFileSignature | None
    metadata: _PlanFileMetadata
    expires_at: float | None = None


class _PlanFileCache:
    """Bounded frontmatter cache invalidated by file mtime and size."""

    def __init__(self, *, max_entries: int = _CACHE_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[Path, _PlanFileCacheEntry] = OrderedDict()
        self._lock = RLock()

    def get(self, path: Path) -> _PlanFileMetadata:
        normalized = path.expanduser().resolve(strict=False)
        now = monotonic()
        try:
            stat = normalized.stat()
            signature: PlanFileSignature | None = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None

        with self._lock:
            entry = self._entries.get(normalized)
            if entry is not None:
                self._entries.move_to_end(normalized)
                if signature is not None and entry.signature == signature:
                    return entry.metadata
                if (
                    signature is None
                    and entry.signature is None
                    and entry.expires_at is not None
                    and entry.expires_at > now
                ):
                    return entry.metadata

            metadata = self._load(normalized, exists=signature is not None)
            result = _PlanFileCacheEntry(
                signature=signature,
                metadata=metadata,
                expires_at=(now + _NEGATIVE_TTL_SECONDS if signature is None else None),
            )
            self._entries[normalized] = result
            self._entries.move_to_end(normalized)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return metadata

    @staticmethod
    def _load(path: Path, *, exists: bool) -> _PlanFileMetadata:
        if not exists:
            return _PlanFileMetadata(None, None, False, False, False)

        readable = os.access(path, os.R_OK)
        if not readable:
            return _PlanFileMetadata(None, None, True, False, False)

        frontmatter, error = read_plan_frontmatter(path)
        if error is not None:
            return _PlanFileMetadata(None, None, True, True, False)

        raw_goal = frontmatter.get("goal")
        goal = " ".join(raw_goal.split()) if isinstance(raw_goal, str) else None
        normalized_tier = normalize_plan_tier(frontmatter.get("tier"))
        authored_tier: AuthoredPlanTier | None = None
        if normalized_tier == "tale":
            authored_tier = "tale"
        elif normalized_tier == "epic":
            authored_tier = "epic"
        return _PlanFileMetadata(
            goal=goal or None,
            authored_tier=authored_tier,
            exists=True,
            readable=True,
            frontmatter_readable=True,
        )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class _PlanAssociationCache:
    """Short-lived cache for direct and bead-derived plan resolution."""

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


_PLAN_FILE_CACHE = _PlanFileCache()
_PLAN_ASSOCIATION_CACHE = _PlanAssociationCache()


def associated_plan_cache_key(agent: Agent) -> tuple[object, ...]:
    """Return the memory-only inputs that can change plan enrichment."""
    return (
        agent.plan_path,
        agent.archived_plan_path,
        agent.sdd_plan_path,
        agent.plan_committed,
        agent.plan_action,
        agent.epic_bead_id,
        agent.phase_bead_id,
        agent.agent_name,
        agent.workspace_dir,
        agent.effective_workspace_num,
    )


def resolve_agent_associated_plan(
    agent: Agent,
    *,
    lookup_session: BeadIssueLookupSession | None = None,
) -> AssociatedPlanSummary | None:
    """Resolve and parse the selected agent's associated plan once.

    This function may touch plan, workspace, and bead storage. Callers must
    keep it inside the existing deferred detail-header enrichment worker.
    """
    archived_path = agent.archived_plan_path
    if (
        archived_path is None
        and agent.plan_path
        and agent.plan_path != agent.sdd_plan_path
    ):
        archived_path = agent.plan_path
    reference = select_canonical_plan_path(
        archived_plan_path=archived_path,
        sdd_plan_path=agent.sdd_plan_path,
        plan_committed=agent.plan_committed,
        plan_action=agent.plan_action,
    )

    source = "direct"
    plan_path: Path | None
    if reference:
        plan_path = _resolve_cached_reference(agent, source, reference)
    else:
        source = "bead"
        bead_id = _agent_bead_id(agent)
        if bead_id is None:
            return None
        key = _association_key(agent, source, bead_id)
        cached = _PLAN_ASSOCIATION_CACHE.get(key)
        if cached is _CACHE_MISS:
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
        else:
            plan_path = cached if isinstance(cached, Path) else None

    if plan_path is None:
        return None

    metadata = _PLAN_FILE_CACHE.get(plan_path)
    committed = _effective_commit_state(agent)
    return AssociatedPlanSummary(
        goal=metadata.goal,
        authored_tier=metadata.authored_tier,
        effective_tier=_effective_tier(agent, metadata.authored_tier),
        actual_path=str(plan_path),
        display_path=_display_plan_path(
            plan_path,
            agent,
            committed=committed is True or source == "bead",
        ),
        committed=committed,
        exists=metadata.exists,
        readable=metadata.readable,
        frontmatter_readable=metadata.frontmatter_readable,
    )


def _resolve_cached_reference(agent: Agent, source: str, reference: str) -> Path:
    key = _association_key(agent, source, reference)
    cached = _PLAN_ASSOCIATION_CACHE.get(key)
    if cached is _CACHE_MISS:
        path = _resolve_plan_reference(reference, agent)
        _PLAN_ASSOCIATION_CACHE.set(key, path)
        return path
    assert isinstance(cached, Path)
    return cached


def _effective_commit_state(agent: Agent) -> bool | None:
    if agent.plan_committed is not None:
        return agent.plan_committed
    if agent.plan_action in {"commit", "tale", "epic"}:
        return True
    return None


def _effective_tier(
    agent: Agent,
    authored_tier: AuthoredPlanTier | None,
) -> AssociatedPlanTier | None:
    if agent.plan_committed is False:
        return "none"
    if agent.plan_action == "epic":
        return "epic"
    if agent.plan_action in {"commit", "tale"}:
        return "plan"
    if authored_tier == "epic":
        return "epic"
    if authored_tier == "tale":
        return "plan"
    if agent.plan_committed is True:
        return "plan"
    return None


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
        parent = _lookup_issue(agent, issue.parent_id, lookup_session=lookup_session)
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
    return (
        source,
        value,
        _agent_project_name(agent),
        _normalized_workspace_dir(agent.workspace_dir),
        agent.effective_workspace_num or 1,
    )


def _resolve_plan_reference(reference: str, agent: Agent) -> Path:
    raw_path = Path(reference).expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve(strict=False)

    workspace_dir = _agent_workspace_dir(agent)
    workspace_num = agent.effective_workspace_num or 1
    candidates: list[Path] = []
    if workspace_dir is not None:
        candidates.append(workspace_dir / raw_path)
        primary = _primary_workspace_dir(workspace_dir, workspace_num)
        if primary is not None:
            candidates.append(primary / raw_path)
        candidates.extend(_sdd_plan_candidates(workspace_dir, workspace_num, raw_path))
    if not candidates:
        candidates.append(raw_path)

    normalized = _dedupe_paths(candidates)
    for candidate in normalized:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return normalized[0]


def _display_plan_path(
    path: Path,
    agent: Agent,
    *,
    committed: bool,
) -> str:
    if committed:
        workspace_dir = _agent_workspace_dir(agent)
        if workspace_dir is not None:
            try:
                return path.relative_to(workspace_dir).as_posix()
            except ValueError:
                pass
    return shorten_path(str(path))


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
