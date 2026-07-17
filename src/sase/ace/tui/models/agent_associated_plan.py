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
        agent.plan_committed,
        agent.plan_action,
        agent.epic_bead_id,
        agent.phase_bead_id,
        agent.agent_family_role,
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

    # A modern phase worker normally has all identity inputs in agent_meta.json.
    # Explicit family-role metadata remains authoritative when a damaged or
    # historical record has lost its child-specific phase bead field. Keep the
    # failure mode bead-only and never fall back to mutable bead storage.
    explicit_phase = agent.agent_family_role == "phase"
    phase_bead_id = agent.phase_bead_id
    if phase_bead_id is None and explicit_phase:
        phase_bead_id = derive_agent_bead_id_from_name(agent.agent_name)
    phase_display = phase_bead_id or (agent.agent_name if explicit_phase else None)
    if agent.phase_bead_id or explicit_phase:
        if not reference:
            return _AgentPlanEnrichment(
                role="phase",
                bead_display=phase_display,
                associated_plan=None,
                resolved_plan_path=None,
            )
        plan_path = _resolve_cached_reference(agent, "direct", reference)
        metadata = _load_plan_metadata(plan_path)
        if phase_bead_id is not None:
            phase_display = _phase_bead_display(
                metadata,
                epic_bead_id=agent.epic_bead_id,
                phase_bead_id=phase_bead_id,
                plan_reference=reference,
            )
        return _AgentPlanEnrichment(
            role="phase",
            bead_display=phase_display,
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

    metadata = _load_plan_metadata(plan_path)
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
