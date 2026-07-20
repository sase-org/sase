"""Plan-file loading and summary construction for agent plan enrichment."""

from __future__ import annotations

from pathlib import Path

from sase.core.artifact_file_helpers import select_canonical_plan_path

from ._agent_associated_plan_paths import display_plan_path
from ._agent_associated_plan_types import (
    AssociatedPlanPhaseAvailability,
    AssociatedPlanSummary,
    AssociatedPlanTier,
    AuthoredPlanTier,
    PlanFileMetadata,
)
from .agent import Agent


def build_associated_plan_summary(
    agent: Agent,
    plan_path: Path,
    metadata: PlanFileMetadata,
    *,
    committed: bool | None,
    display_committed: bool,
    known_epic: bool,
) -> AssociatedPlanSummary:
    """Build the render-ready summary shared by agent and phase plans."""
    availability = _phase_availability(
        agent,
        metadata,
        known_epic=known_epic,
    )
    return AssociatedPlanSummary(
        title=metadata.title,
        goal=metadata.goal,
        authored_tier=metadata.authored_tier,
        effective_tier=_effective_tier(
            agent,
            metadata.authored_tier,
            committed=committed,
        ),
        actual_path=str(plan_path),
        display_path=display_plan_path(
            plan_path,
            agent,
            committed=display_committed,
        ),
        committed=committed,
        exists=metadata.exists,
        readable=metadata.readable,
        frontmatter_readable=metadata.frontmatter_readable,
        phase_availability=availability,
        phases=(metadata.phases if availability == "available" else ()),
        validation_ok=metadata.validation_ok,
        validation_diagnostics=metadata.validation_diagnostics,
    )


def direct_plan_reference(agent: Agent) -> str | None:
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


def _phase_availability(
    agent: Agent,
    metadata: PlanFileMetadata,
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


def effective_commit_state(agent: Agent) -> bool | None:
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
