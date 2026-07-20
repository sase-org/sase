"""Associated-plan resolution for deferred Agents-tab detail enrichment.

This module is the stable import facade. Value types, caches, and filesystem
path handling live in focused sibling modules while role-aware orchestration
remains here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from sase.agent.bead_display import (
    BeadIssueLookupSession,
    derive_agent_bead_id_from_name,
    lookup_bead_issue,
    normalize_bead_text,
)
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead.phase_description import generated_phase_description
from sase.core.artifact_file_helpers import select_canonical_plan_path
from sase.sdd.plan_validate import validate_plan

from ._agent_associated_plan_cache import (
    _CACHE_MISS,
    _PLAN_ASSOCIATION_CACHE,
    _PLAN_FILE_CACHE,
    PlanAssociationCache as _PlanAssociationCache,
    PlanFileCache as _PlanFileCache,
)
from ._agent_associated_plan_paths import (
    agent_project_name as _agent_project_name,
    association_key as _association_key,
    display_plan_path as _display_plan_path,
    resolve_plan_reference as _resolve_plan_reference,
)
from ._agent_associated_plan_types import (
    AgentPlanRole,
    AssociatedPlanPhaseAvailability,
    AssociatedPlanPhaseSummary as AssociatedPlanPhaseSummary,
    AssociatedPlanSummary as AssociatedPlanSummary,
    AssociatedPlanTier,
    AuthoredPlanTier,
    AgentPlanEnrichment as _AgentPlanEnrichment,
    _InitialAgentPlanRole,
    PhaseBeadSummary as PhaseBeadSummary,
    PlanFileMetadata as _PlanFileMetadata,
    ResolvedPlanAssociation as _ResolvedPlanAssociation,
)
from .agent import Agent


def associated_plan_cache_key(agent: Agent) -> tuple[object, ...]:
    """Return the memory-only inputs that can change plan enrichment."""
    return (
        agent.plan_path,
        agent.archived_plan_path,
        agent.sdd_plan_path,
        agent.epic_plan_ref,
        agent.plan_committed,
        agent.plan_action,
        agent.epic_bead_id,
        agent.phase_bead_id,
        agent.agent_family_role,
        agent.agent_name,
        agent.project_file,
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
    Modern phase metadata takes an explicit parent-epic reference and never
    consults bead storage; legacy rows retain the bounded local compatibility
    lookup.
    """
    initial_role = _initial_agent_plan_role(agent)
    role: AgentPlanRole = "phase" if initial_role == "ambiguous" else initial_role
    association: _ResolvedPlanAssociation | None = None
    if initial_role == "phase":
        return _resolve_phase_plan_enrichment(
            agent,
            lookup_session=lookup_session,
        )
    if initial_role == "ambiguous":
        bead_id = derive_agent_bead_id_from_name(agent.agent_name)
        if bead_id is not None:
            association = _cached_bead_plan_association(
                agent,
                bead_id,
                source="bead-role",
                lookup_session=lookup_session,
            )
        if association is None or association.role != "land":
            if association is None or association.path is None:
                # A confirmed legacy phase without an epic-plan association
                # keeps the compact historical ``Bead:`` row. Only promote
                # it into the structured BEAD lane once a parent plan can be
                # resolved; unconfirmed dotted names remain invisible.
                return _AgentPlanEnrichment("phase", None, None, ())
            return _resolve_phase_plan_enrichment(
                agent,
                lookup_session=lookup_session,
                parent_association=association,
            )
        role = "land"

    reference = _direct_plan_reference(agent)
    plan_path: Path | None
    source = "direct"
    known_epic = False
    if reference:
        plan_path = _resolve_cached_reference(agent, source, reference)
    else:
        source = "bead"
        bead_id = _agent_bead_id(agent)
        if bead_id is None:
            return _AgentPlanEnrichment(role, None, None, ())
        if association is None:
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
        # candidate). Explicit modern phases returned above remain phase-local
        # and authoritative even without a usable plan reference.
        phase_bead = None
        if role == "phase" and association is not None:
            phase_id = association.phase_bead_id
            if phase_id is not None:
                phase_bead = _unavailable_phase_bead(phase_id)
        return _AgentPlanEnrichment(role, phase_bead, None, ())

    metadata = _load_plan_metadata(plan_path)
    if role == "phase":
        epic_bead_id = association.epic_bead_id if association is not None else None
        phase_bead_id = association.phase_bead_id if association is not None else None
        plan_reference = (
            reference
            or (association.plan_reference if association is not None else None)
            or str(plan_path)
        )
        phase_bead = (
            _phase_bead_summary(
                metadata,
                agent=agent,
                epic_bead_id=epic_bead_id,
                phase_bead_id=phase_bead_id,
                plan_reference=plan_reference,
                plan_path=plan_path,
            )
            if phase_bead_id
            else None
        )
        return _AgentPlanEnrichment(
            role="phase",
            phase_bead=phase_bead,
            associated_plan=None,
            resolved_plan_paths=(str(plan_path),),
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
        validation_ok=metadata.validation_ok,
        validation_diagnostics=metadata.validation_diagnostics,
    )
    return _AgentPlanEnrichment(
        role=role,
        phase_bead=None,
        associated_plan=summary,
        resolved_plan_paths=(str(plan_path),),
    )


def _resolve_phase_plan_enrichment(
    agent: Agent,
    *,
    lookup_session: BeadIssueLookupSession | None,
    parent_association: _ResolvedPlanAssociation | None = None,
) -> _AgentPlanEnrichment:
    """Resolve a phase's parent BEAD and authored PLAN independently."""
    phase_bead_id = agent.phase_bead_id or _derived_phase_bead_id(agent)
    epic_bead_id = agent.epic_bead_id
    parent_reference = agent.epic_plan_ref
    parent_path: Path | None = None

    if not parent_reference and agent.agent_family_role == "phase":
        # Damaged pre-field phase rows carried the parent epic in the generic
        # plan slots. Preserve their no-bead-lookup privacy behavior while
        # modern rows use the explicit parent reference above.
        parent_reference = _direct_plan_reference(agent)

    if parent_reference:
        parent_path = _resolve_cached_reference(
            agent,
            "parent-direct",
            parent_reference,
        )
    else:
        bead_id = phase_bead_id or derive_agent_bead_id_from_name(agent.agent_name)
        if parent_association is None and bead_id is not None:
            parent_association = _cached_bead_plan_association(
                agent,
                bead_id,
                source="bead-parent",
                lookup_session=lookup_session,
            )
        if parent_association is not None:
            parent_path = parent_association.path
            parent_reference = parent_association.plan_reference
            epic_bead_id = parent_association.epic_bead_id or epic_bead_id
            phase_bead_id = parent_association.phase_bead_id or phase_bead_id

    phase_bead: PhaseBeadSummary | None = None
    if phase_bead_id is not None:
        if parent_path is None:
            phase_bead = _unavailable_phase_bead(
                phase_bead_id,
                plan_reference=parent_reference,
            )
        else:
            parent_metadata = _load_plan_metadata(parent_path)
            phase_bead = _phase_bead_summary(
                parent_metadata,
                agent=agent,
                epic_bead_id=epic_bead_id,
                phase_bead_id=phase_bead_id,
                plan_reference=parent_reference or str(parent_path),
                plan_path=parent_path,
            )

    associated_plan, authored_path = _resolve_phase_authored_plan(
        agent,
        parent_path=parent_path,
    )
    return _AgentPlanEnrichment(
        role="phase",
        phase_bead=phase_bead,
        associated_plan=associated_plan,
        resolved_plan_paths=_resolved_plan_paths(parent_path, authored_path),
    )


def _resolve_phase_authored_plan(
    agent: Agent,
    *,
    parent_path: Path | None,
) -> tuple[AssociatedPlanSummary | None, Path | None]:
    """Return a PLAN only when the phase has a distinct authored artifact."""
    archived_reference = agent.archived_plan_path
    if (
        archived_reference is None
        and agent.plan_path
        and agent.plan_path != agent.sdd_plan_path
    ):
        archived_reference = agent.plan_path

    archived_path = _resolve_distinct_authored_reference(
        agent,
        "authored-archive",
        archived_reference,
        parent_path=parent_path,
    )
    sdd_path = _resolve_distinct_authored_reference(
        agent,
        "authored-sdd",
        agent.sdd_plan_path,
        parent_path=parent_path,
    )
    has_handoff_evidence = bool(
        archived_path is not None
        or agent.plan_action is not None
        or (
            sdd_path is not None
            and agent.plan_committed is not None
            and agent.agent_family_role in {"code", "plan", "feedback"}
        )
    )
    if not has_handoff_evidence:
        return None, None
    if archived_path is None and sdd_path is None:
        return None, None

    selected_path: Path
    if archived_path is not None and sdd_path is not None:
        selected_reference = select_canonical_plan_path(
            archived_plan_path=str(archived_path),
            sdd_plan_path=str(sdd_path),
            plan_committed=agent.plan_committed,
            plan_action=agent.plan_action,
        )
        selected_path = Path(selected_reference or archived_path)
    else:
        only_path = archived_path or sdd_path
        assert only_path is not None
        selected_path = only_path

    selected_is_sdd = sdd_path is not None and _same_plan_path(
        selected_path,
        sdd_path,
    )
    if selected_is_sdd:
        committed = _effective_commit_state(agent)
    elif agent.plan_committed is False or agent.plan_action == "approve":
        committed = False
    elif sdd_path is None:
        # A distinct archive with no authored SDD handoff is a submitted plan;
        # the inherited parent epic's commit bit does not apply to it.
        committed = False
    else:
        committed = _effective_commit_state(agent)

    metadata = _load_plan_metadata(selected_path)
    phase_availability = _phase_availability(
        agent,
        metadata,
        known_epic=False,
    )
    summary = AssociatedPlanSummary(
        title=metadata.title,
        goal=metadata.goal,
        authored_tier=metadata.authored_tier,
        effective_tier=_effective_tier(
            agent,
            metadata.authored_tier,
            committed=committed,
        ),
        actual_path=str(selected_path),
        display_path=_display_plan_path(
            selected_path,
            agent,
            committed=committed is True,
        ),
        committed=committed,
        exists=metadata.exists,
        readable=metadata.readable,
        frontmatter_readable=metadata.frontmatter_readable,
        phase_availability=phase_availability,
        phases=(metadata.phases if phase_availability == "available" else ()),
        validation_ok=metadata.validation_ok,
        validation_diagnostics=metadata.validation_diagnostics,
    )
    return summary, selected_path


def _resolve_distinct_authored_reference(
    agent: Agent,
    source: str,
    reference: str | None,
    *,
    parent_path: Path | None,
) -> Path | None:
    if not reference:
        return None
    path = _resolve_cached_reference(agent, source, reference)
    if parent_path is not None and _same_plan_path(path, parent_path):
        return None
    return path


def _same_plan_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve(strict=False) == right.expanduser().resolve(
        strict=False
    )


def _resolved_plan_paths(*paths: Path | None) -> tuple[str, ...]:
    seen: set[Path] = set()
    resolved: list[str] = []
    for path in paths:
        if path is None:
            continue
        normalized = path.expanduser().resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        resolved.append(str(path))
    return tuple(resolved)


def _load_plan_metadata(path: Path) -> _PlanFileMetadata:
    return _PLAN_FILE_CACHE.get(
        path,
        is_readable=lambda candidate: os.access(candidate, os.R_OK),
        validate=validate_plan,
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
    if agent.phase_bead_id or agent.agent_family_role == "phase":
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


def _phase_bead_summary(
    metadata: _PlanFileMetadata,
    *,
    agent: Agent,
    epic_bead_id: str | None,
    phase_bead_id: str,
    plan_reference: str,
    plan_path: Path,
) -> PhaseBeadSummary:
    """Build one render-ready selected-phase summary from validated order."""
    summary = _unavailable_phase_bead(
        phase_bead_id,
        agent=agent,
        metadata=metadata,
        plan_reference=plan_reference,
        plan_path=plan_path,
    )
    phase_index = _phase_index(epic_bead_id, phase_bead_id)
    if (
        phase_index is None
        or metadata.phase_availability != "available"
        or phase_index >= len(metadata.phases)
    ):
        return summary

    phase = metadata.phases[phase_index]
    description = phase.description or generated_phase_description(
        plan_reference,
        phase.id,
    )
    normalized = normalize_bead_text(description)
    return PhaseBeadSummary(
        id=phase_bead_id,
        description=normalized or None,
        actual_plan_path=summary.actual_plan_path,
        display_plan_path=summary.display_plan_path,
        plan_exists=summary.plan_exists,
        plan_readable=summary.plan_readable,
        epic_title=metadata.title,
        size=phase.size,
    )


def _unavailable_phase_bead(
    phase_bead_id: str,
    *,
    agent: Agent | None = None,
    metadata: _PlanFileMetadata | None = None,
    plan_reference: str | None = None,
    plan_path: Path | None = None,
) -> PhaseBeadSummary:
    """Return a phase identity with honest optional-field fallbacks."""
    actual_path = str(plan_path) if plan_path is not None else None
    display_path = _phase_display_plan_path(
        plan_reference,
        plan_path=plan_path,
        agent=agent,
    )
    return PhaseBeadSummary(
        id=phase_bead_id,
        description=None,
        actual_plan_path=actual_path,
        display_plan_path=display_path,
        plan_exists=metadata.exists if metadata is not None else False,
        plan_readable=metadata.readable if metadata is not None else False,
        epic_title=None,
        size=None,
    )


def _phase_display_plan_path(
    reference: str | None,
    *,
    plan_path: Path | None,
    agent: Agent | None,
) -> str | None:
    """Keep canonical relative references while resolving only navigation paths."""
    if reference:
        raw_reference = Path(reference).expanduser()
        if not raw_reference.is_absolute():
            return raw_reference.as_posix()
    if plan_path is not None and agent is not None:
        return _display_plan_path(plan_path, agent, committed=True)
    return None


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


def _derived_phase_bead_id(agent: Agent) -> str | None:
    """Recover only a structurally trustworthy child ID from a phase name."""
    candidate = derive_agent_bead_id_from_name(agent.agent_name)
    if candidate is None:
        return None
    if agent.epic_bead_id:
        return (
            candidate
            if _phase_index(agent.epic_bead_id, candidate) is not None
            else None
        )
    _, separator, ordinal = candidate.rpartition(".")
    return candidate if separator and ordinal.isdigit() and int(ordinal) > 0 else None


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
    *,
    committed: bool | None = None,
) -> AssociatedPlanTier | None:
    if agent.plan_action == "approve":
        return "plan"
    if agent.plan_action in {"commit", "tale"}:
        return "tale"
    if agent.plan_action == "epic":
        return "epic"
    if agent.plan_action is not None:
        return None
    if committed is None:
        committed = agent.plan_committed
    if committed is False:
        return "plan"
    if authored_tier == "epic":
        return "epic"
    if authored_tier == "tale":
        return "tale"
    if committed is True:
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
