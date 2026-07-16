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
    normalize_bead_text,
)
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead.phase_description import generated_phase_description
from sase.core.agent_artifact_helpers import select_canonical_plan_path
from sase.core.paths import shorten_path
from sase.sdd.plan_tiers import normalize_plan_tier, parse_plan_frontmatter
from sase.sdd.plan_validate import ValidatedPlanPhase, validate_plan

from .agent import Agent

_CACHE_MAX_ENTRIES = 256
_ASSOCIATION_TTL_SECONDS = 60.0
_NEGATIVE_TTL_SECONDS = 5.0
_CACHE_MISS: Final = object()

AssociatedPlanTier = Literal["plan", "tale", "epic"]
AuthoredPlanTier = Literal["tale", "epic"]
AgentPlanRole = Literal["ordinary", "author", "phase", "land"]
_InitialAgentPlanRole = Literal[
    "ordinary",
    "author",
    "phase",
    "land",
    "ambiguous",
]
AssociatedPlanPhaseAvailability = Literal[
    "not-applicable",
    "available",
    "unavailable",
]
PlanAssociationCacheKey = tuple[str, str, str | None, str | None, int]
PlanFileSignature = tuple[int, int]


@dataclass(frozen=True, slots=True)
class AssociatedPlanPhaseSummary:
    """Immutable normalized epic phase consumed by the render path."""

    id: str
    title: str
    depends_on: tuple[str, ...]
    description: str | None
    model: str | None


@dataclass(frozen=True, slots=True)
class AssociatedPlanSummary:
    """Immutable plan metadata consumed by the in-memory render path."""

    title: str | None
    goal: str | None
    authored_tier: AuthoredPlanTier | None
    effective_tier: AssociatedPlanTier | None
    actual_path: str
    display_path: str
    committed: bool | None
    exists: bool
    readable: bool
    frontmatter_readable: bool
    phase_availability: AssociatedPlanPhaseAvailability
    phases: tuple[AssociatedPlanPhaseSummary, ...]


@dataclass(frozen=True, slots=True)
class _AgentPlanEnrichment:
    """Role-aware plan result consumed by deferred detail enrichment.

    Phase workers deliberately carry ``associated_plan=None``. Their resolved
    plan path is retained only so the generic artifact list can avoid exposing
    the same epic plan as unrelated metadata.
    """

    role: AgentPlanRole
    bead_display: str | None
    associated_plan: AssociatedPlanSummary | None
    resolved_plan_path: str | None


@dataclass(frozen=True, slots=True)
class _PlanFileMetadata:
    title: str | None
    goal: str | None
    authored_tier: AuthoredPlanTier | None
    exists: bool
    readable: bool
    frontmatter_readable: bool
    phase_availability: AssociatedPlanPhaseAvailability
    phases: tuple[AssociatedPlanPhaseSummary, ...]


@dataclass(frozen=True, slots=True)
class _PlanFileCacheEntry:
    signature: PlanFileSignature | None
    metadata: _PlanFileMetadata
    expires_at: float | None = None


@dataclass(frozen=True, slots=True)
class _ResolvedPlanAssociation:
    path: Path | None
    known_epic: bool = False
    role: Literal["phase", "land"] | None = None
    plan_reference: str | None = None
    epic_bead_id: str | None = None
    phase_bead_id: str | None = None


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
            return _PlanFileMetadata(
                title=None,
                goal=None,
                authored_tier=None,
                exists=False,
                readable=False,
                frontmatter_readable=False,
                phase_availability="unavailable",
                phases=(),
            )

        readable = os.access(path, os.R_OK)
        if not readable:
            return _PlanFileMetadata(
                title=None,
                goal=None,
                authored_tier=None,
                exists=True,
                readable=False,
                frontmatter_readable=False,
                phase_availability="unavailable",
                phases=(),
            )

        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return _PlanFileMetadata(
                title=None,
                goal=None,
                authored_tier=None,
                exists=True,
                readable=False,
                frontmatter_readable=False,
                phase_availability="unavailable",
                phases=(),
            )
        except UnicodeDecodeError:
            return _PlanFileMetadata(
                title=None,
                goal=None,
                authored_tier=None,
                exists=True,
                readable=True,
                frontmatter_readable=False,
                phase_availability="unavailable",
                phases=(),
            )

        frontmatter, error = parse_plan_frontmatter(content)
        if error is not None:
            return _PlanFileMetadata(
                title=None,
                goal=None,
                authored_tier=None,
                exists=True,
                readable=True,
                frontmatter_readable=False,
                phase_availability="unavailable",
                phases=(),
            )

        raw_title = frontmatter.get("title")
        title = " ".join(raw_title.split()) if isinstance(raw_title, str) else None
        raw_goal = frontmatter.get("goal")
        goal = " ".join(raw_goal.split()) if isinstance(raw_goal, str) else None
        normalized_tier = normalize_plan_tier(frontmatter.get("tier"))
        authored_tier: AuthoredPlanTier | None = None
        if normalized_tier == "tale":
            authored_tier = "tale"
        elif normalized_tier == "epic":
            authored_tier = "epic"

        phase_availability: AssociatedPlanPhaseAvailability = "not-applicable"
        phases: tuple[AssociatedPlanPhaseSummary, ...] = ()
        if authored_tier == "epic":
            phase_availability = "unavailable"
            try:
                validation = validate_plan(content, "epic")
            except Exception:
                validation = None
            if validation is not None and validation.ok and validation.plan is not None:
                phases = tuple(
                    _phase_summary(phase) for phase in validation.plan.phases
                )
                phase_availability = "available"
        return _PlanFileMetadata(
            title=title or None,
            goal=goal or None,
            authored_tier=authored_tier,
            exists=True,
            readable=True,
            frontmatter_readable=True,
            phase_availability=phase_availability,
            phases=phases,
        )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class _PlanAssociationCache:
    """Short-lived cache for direct and bead-derived plan resolution."""

    def __init__(self, *, max_entries: int = _CACHE_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[
            PlanAssociationCacheKey, tuple[float, _ResolvedPlanAssociation]
        ] = OrderedDict()
        self._lock = RLock()

    def get(self, key: PlanAssociationCacheKey) -> _ResolvedPlanAssociation | object:
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return _CACHE_MISS
            expires_at, association = entry
            if expires_at <= now:
                del self._entries[key]
                return _CACHE_MISS
            self._entries.move_to_end(key)
            return association

    def set(
        self,
        key: PlanAssociationCacheKey,
        association: _ResolvedPlanAssociation,
    ) -> None:
        ttl = (
            _NEGATIVE_TTL_SECONDS
            if association.path is None
            else _ASSOCIATION_TTL_SECONDS
        )
        with self._lock:
            self._entries[key] = (monotonic() + ttl, association)
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


def resolve_agent_plan_enrichment(
    agent: Agent,
    *,
    lookup_session: BeadIssueLookupSession | None = None,
) -> _AgentPlanEnrichment:
    """Resolve role-specific plan metadata for the selected agent once.

    This function may touch plan, workspace, and bead storage. Callers must
    keep it inside the existing deferred detail-header enrichment worker.
    Modern phase metadata takes a direct plan path and never consults bead
    storage; legacy ambiguous names retain the bounded compatibility lookup.
    """
    reference = _direct_plan_reference(agent)
    initial_role = _initial_agent_plan_role(agent)
    role: AgentPlanRole = "phase" if initial_role == "ambiguous" else initial_role
    plan_path: Path | None

    # A modern phase worker has all identity inputs in agent_meta.json. Keep
    # the failure mode bead-only even when its plan reference is missing or
    # damaged, and never fall back to mutable bead storage.
    if agent.phase_bead_id:
        if not reference:
            return _AgentPlanEnrichment(
                role="phase",
                bead_display=agent.phase_bead_id,
                associated_plan=None,
                resolved_plan_path=None,
            )
        plan_path = _resolve_cached_reference(agent, "direct", reference)
        metadata = _PLAN_FILE_CACHE.get(plan_path)
        return _AgentPlanEnrichment(
            role="phase",
            bead_display=_phase_bead_display(
                metadata,
                epic_bead_id=agent.epic_bead_id,
                phase_bead_id=agent.phase_bead_id,
                plan_reference=reference,
            ),
            associated_plan=None,
            resolved_plan_path=str(plan_path),
        )

    source = "direct"
    known_epic = False
    association: _ResolvedPlanAssociation | None = None
    if reference:
        plan_path = _resolve_cached_reference(agent, source, reference)
        if initial_role == "ambiguous":
            bead_id = derive_agent_bead_id_from_name(agent.agent_name)
            if bead_id is not None:
                association = _cached_bead_plan_association(
                    agent,
                    bead_id,
                    source="bead-role",
                    lookup_session=lookup_session,
                )
                role = association.role or "phase"
    else:
        source = "bead"
        bead_id = _agent_bead_id(agent)
        if bead_id is None:
            return _AgentPlanEnrichment(role, None, None, None)
        association = _cached_bead_plan_association(
            agent,
            bead_id,
            source=source,
            lookup_session=lookup_session,
        )
        plan_path = association.path
        known_epic = association.known_epic
        if initial_role in {"ordinary", "ambiguous"} and association.role is not None:
            role = association.role

    if plan_path is None:
        # Legacy rows still use the generic confirmation cache for bead-only
        # display. Returning a bare id here would let ambient/stale bead-store
        # state overwrite a richer confirmed description (or surface a cold
        # candidate). Explicit modern phases returned above remain bead-only
        # and authoritative even without a usable plan reference.
        return _AgentPlanEnrichment(role, None, None, None)

    metadata = _PLAN_FILE_CACHE.get(plan_path)
    if role == "phase":
        epic_bead_id = association.epic_bead_id if association is not None else None
        phase_bead_id = association.phase_bead_id if association is not None else None
        plan_reference = (
            reference
            or (association.plan_reference if association is not None else None)
            or str(plan_path)
        )
        bead_display = (
            _phase_bead_display(
                metadata,
                epic_bead_id=epic_bead_id,
                phase_bead_id=phase_bead_id,
                plan_reference=plan_reference,
            )
            if phase_bead_id
            else None
        )
        return _AgentPlanEnrichment(
            role="phase",
            bead_display=bead_display,
            associated_plan=None,
            resolved_plan_path=str(plan_path),
        )

    committed = _effective_commit_state(agent)
    phase_availability = _phase_availability(
        agent,
        metadata,
        known_epic=known_epic,
    )
    summary = AssociatedPlanSummary(
        title=metadata.title,
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
        phase_availability=phase_availability,
        phases=(metadata.phases if phase_availability == "available" else ()),
    )
    return _AgentPlanEnrichment(
        role=role,
        bead_display=None,
        associated_plan=summary,
        resolved_plan_path=str(plan_path),
    )


def _direct_plan_reference(agent: Agent) -> str | None:
    archived_path = agent.archived_plan_path
    if (
        archived_path is None
        and agent.plan_path
        and agent.plan_path != agent.sdd_plan_path
    ):
        archived_path = agent.plan_path
    return select_canonical_plan_path(
        archived_plan_path=archived_path,
        sdd_plan_path=agent.sdd_plan_path,
        plan_committed=agent.plan_committed,
        plan_action=agent.plan_action,
    )


def _initial_agent_plan_role(agent: Agent) -> _InitialAgentPlanRole:
    if agent.phase_bead_id:
        return "phase"

    derived_bead_id = derive_agent_bead_id_from_name(agent.agent_name)
    if agent.epic_bead_id:
        if derived_bead_id == agent.epic_bead_id:
            return "land"
        return "author"

    if agent.agent_name and agent.agent_name.endswith(".land"):
        return "land"
    if derived_bead_id is not None:
        # Child phase IDs append a numeric component. A nested epic ID can
        # have the same shape, so legacy dotted names stay ambiguous until a
        # bounded issue lookup confirms whether the exact bead is epic/phase.
        return "ambiguous" if "." in derived_bead_id else "land"
    if agent.plan_action == "epic":
        return "author"
    return "ordinary"


def _phase_bead_display(
    metadata: _PlanFileMetadata,
    *,
    epic_bead_id: str | None,
    phase_bead_id: str,
    plan_reference: str,
) -> str:
    """Build one phase's bead display from validated frontmatter order."""
    phase_index = _phase_index(epic_bead_id, phase_bead_id)
    if (
        phase_index is None
        or metadata.phase_availability != "available"
        or phase_index >= len(metadata.phases)
    ):
        return phase_bead_id

    phase = metadata.phases[phase_index]
    description = phase.description or generated_phase_description(
        plan_reference,
        phase.id,
    )
    normalized = normalize_bead_text(description)
    return f"{phase_bead_id} - {normalized}" if normalized else phase_bead_id


def _phase_index(epic_bead_id: str | None, phase_bead_id: str) -> int | None:
    if not epic_bead_id:
        return None
    prefix = f"{epic_bead_id}."
    if not phase_bead_id.startswith(prefix):
        return None
    ordinal = phase_bead_id[len(prefix) :]
    if not ordinal.isdigit():
        return None
    value = int(ordinal)
    return value - 1 if value > 0 else None


def _phase_summary(phase: ValidatedPlanPhase) -> AssociatedPlanPhaseSummary:
    return AssociatedPlanPhaseSummary(
        id=phase.id,
        title=phase.title,
        depends_on=phase.depends_on,
        description=phase.description,
        model=phase.model,
    )


def _phase_availability(
    agent: Agent,
    metadata: _PlanFileMetadata,
    *,
    known_epic: bool,
) -> AssociatedPlanPhaseAvailability:
    if metadata.authored_tier == "tale":
        return "not-applicable"
    if metadata.authored_tier == "epic":
        return metadata.phase_availability
    if (
        known_epic
        or agent.plan_action == "epic"
        or agent.epic_bead_id
        or agent.phase_bead_id
    ):
        return "unavailable"
    return "not-applicable"


def _resolve_cached_reference(agent: Agent, source: str, reference: str) -> Path:
    key = _association_key(agent, source, reference)
    cached = _PLAN_ASSOCIATION_CACHE.get(key)
    if cached is _CACHE_MISS:
        path = _resolve_plan_reference(reference, agent)
        _PLAN_ASSOCIATION_CACHE.set(key, _ResolvedPlanAssociation(path))
        return path
    assert isinstance(cached, _ResolvedPlanAssociation)
    assert cached.path is not None
    return cached.path


def _cached_bead_plan_association(
    agent: Agent,
    bead_id: str,
    *,
    source: str,
    lookup_session: BeadIssueLookupSession | None,
) -> _ResolvedPlanAssociation:
    key = _association_key(agent, source, bead_id)
    cached = _PLAN_ASSOCIATION_CACHE.get(key)
    if cached is not _CACHE_MISS:
        assert isinstance(cached, _ResolvedPlanAssociation)
        return cached

    if lookup_session is None:
        with BeadIssueLookupSession() as owned_session:
            association = _resolve_bead_plan_association(
                agent,
                bead_id,
                lookup_session=owned_session,
            )
    else:
        association = _resolve_bead_plan_association(
            agent,
            bead_id,
            lookup_session=lookup_session,
        )
    _PLAN_ASSOCIATION_CACHE.set(key, association)
    return association


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
    if agent.plan_action == "approve":
        return "plan"
    if agent.plan_action in {"commit", "tale"}:
        return "tale"
    if agent.plan_action == "epic":
        return "epic"
    if agent.plan_action is not None:
        return None
    if agent.plan_committed is False:
        return "plan"
    if authored_tier == "epic":
        return "epic"
    if authored_tier == "tale":
        return "tale"
    if agent.plan_committed is True:
        return "tale"
    return None


def _resolve_bead_plan_association(
    agent: Agent,
    bead_id: str,
    *,
    lookup_session: BeadIssueLookupSession,
) -> _ResolvedPlanAssociation:
    issue = _lookup_issue(agent, bead_id, lookup_session=lookup_session)
    if issue is None:
        return _ResolvedPlanAssociation(None)
    is_phase = issue.issue_type is IssueType.PHASE
    is_epic = issue.issue_type is IssueType.PLAN and issue.tier is BeadTier.EPIC
    role: Literal["phase", "land"] | None = (
        "phase" if is_phase else ("land" if is_epic else None)
    )
    epic_bead_id = issue.parent_id if is_phase else (issue.id if is_epic else None)
    phase_bead_id = issue.id if is_phase else None
    known_epic = is_phase or is_epic
    design = issue.design.strip()
    if not design and issue.parent_id:
        parent = _lookup_issue(agent, issue.parent_id, lookup_session=lookup_session)
        if parent is not None:
            design = parent.design.strip()
            known_epic = known_epic or parent.tier is BeadTier.EPIC
            if parent.tier is BeadTier.EPIC:
                epic_bead_id = parent.id
    if not design:
        return _ResolvedPlanAssociation(
            None,
            known_epic=known_epic,
            role=role,
            epic_bead_id=epic_bead_id,
            phase_bead_id=phase_bead_id,
        )
    return _ResolvedPlanAssociation(
        _resolve_plan_reference(design, agent),
        known_epic=known_epic,
        role=role,
        plan_reference=design,
        epic_bead_id=epic_bead_id,
        phase_bead_id=phase_bead_id,
    )


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
