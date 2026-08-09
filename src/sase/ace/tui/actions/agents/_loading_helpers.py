"""Helper functions and constants for agent loading and filtering."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.agent.status_buckets import (
    ACTIVE_PLAN_HANDOFF_STATUSES,
    APPROVED_PLAN_STATUSES,
    EPIC_APPROVED_STATUS,
    FEEDBACK_STATUS,
    PENDING_PLAN_REVIEW_STATUS_SET,
    PLAN_COMMITTED_STATUS,
    WORKING_PLAN_STATUSES,
)

if TYPE_CHECKING:
    from ....patch import Patch
    from ...models import Agent
    from ...models.agent import AgentType  # noqa: F401
    from ...models.agent_loader import AgentLoadState

from ...models.agent_status import DISMISSABLE_STATUSES
from ...util.trace import tui_trace
from ._refresh_trace import classify_agents_data_cost

# Type alias for tab names
TabName = Literal["artifacts", "agents", "axe"]

# Loaded statuses that mean the agent has resumed past an asking/answered
# pause: it is executing again or a plan-action milestone landed. An in-memory
# QUESTION or ANSWERED override is stale once the loader reports any of these.
_QUESTION_OVERRIDE_PROGRESS_STATUSES = frozenset(
    {
        "RUNNING",
        *ACTIVE_PLAN_HANDOFF_STATUSES,
        "EPIC APPROVED",
        "PLAN COMMITTED",
    }
)

# Durable statuses/actions that prove a notification-installed pending review
# override has been overtaken. Raw runner states deliberately stay out of this
# set: before agent metadata lands, STARTING/RUNNING/WAITING are not evidence
# that the review was resolved and must not make the pending label flicker.
_PENDING_PLAN_OVERRIDE_PROGRESS_STATUSES = frozenset(
    {
        *ACTIVE_PLAN_HANDOFF_STATUSES,
        EPIC_APPROVED_STATUS,
        PLAN_COMMITTED_STATUS,
        "EPIC CREATED",
        "PLAN REJECTED",
        FEEDBACK_STATUS,
        "PLAN DONE",
        "TALE DONE",
    }
)
_PENDING_PLAN_OVERRIDE_PROGRESS_ACTIONS = frozenset(
    {"approve", "tale", "epic", "commit"}
)


@dataclass(frozen=True)
class _AgentDiskLoadResult:
    """Disk-loaded agents plus the artifact-history completeness state."""

    all_agents: list[Agent]
    dismissed_from_loader: list[Agent]
    load_state: AgentLoadState
    dismissed_bundle_identities: set[tuple[AgentType, str, str | None]] = field(
        default_factory=set
    )


def is_always_visible(agent: Agent) -> bool:
    """Check if agent should always be visible (dismissable or running).

    Args:
        agent: The agent to check.

    Returns:
        True if agent should always be visible, False if it's hideable.
    """
    # Workflow children: visibility managed by fold state, not hide toggle
    if agent.is_workflow_child:
        return True

    # Agents marked hidden (via %hide directive, axe-spawned detection, etc.)
    # are hideable (hidden by default, shown with '.' toggle)
    if agent.hidden:
        return False

    return True


def _question_answer_family_key(agent: Agent) -> str | None:
    """Return a stable family key for QUESTION-override answer reconciliation.

    Rows in one agent family share ``agent_family``; sibling continuations
    additionally share ``parent_timestamp``. Either is enough to recognize the
    continuation that answered an asking row's question.
    """
    if agent.agent_family:
        return agent.agent_family
    return agent.parent_timestamp or None


def build_question_answer_family_index(
    agents: list[Agent],
) -> dict[str, list[Agent]]:
    """Index continuation rows that carry persisted question-response metadata.

    Only rows with a ``question_response_path`` are indexed: their presence is
    the loaded-graph proof that a family question was answered and the runner
    spawned a continuation. The index is keyed by family so a stale
    ``QUESTION`` override on an asking row can find the continuation that
    superseded it without any disk reads.
    """
    index: dict[str, list[Agent]] = {}
    for agent in agents:
        if not agent.question_response_path:
            continue
        key = _question_answer_family_key(agent)
        if key is None:
            continue
        index.setdefault(key, []).append(agent)
    return index


def _question_override_answered_by_family(
    agent: Agent,
    override: str,
    family_index: dict[str, list[Agent]],
) -> bool:
    """Return True when a ``QUESTION`` override is overtaken by a loaded answer.

    An asking row keeps a stale ``QUESTION`` override after its question was
    answered out-of-band (e.g. the notification was dismissed before the
    answer, or the row is a historical artifact that predates response-metadata
    persistence). The override is stale once a same-family continuation row —
    one carrying ``question_response_path`` — was launched after this row's
    latest question submission. Gating on the question time keeps a still-open
    follow-up question from being cleared by an earlier answered round.
    """
    if override != "QUESTION" or not agent.questions_times:
        return False
    key = _question_answer_family_key(agent)
    if key is None:
        return False
    threshold = max(agent.questions_times)
    for continuation in family_index.get(key, ()):
        if continuation is agent:
            continue
        launched = continuation.run_start_time or continuation.start_time
        if launched is not None and launched >= threshold:
            return True
    return False


def should_clear_loaded_agent_status_override(
    agent: Agent,
    override: str,
    question_answer_family_index: dict[str, list[Agent]] | None = None,
) -> bool:
    """Return True when a loaded row should discard an in-memory override.

    When *question_answer_family_index* is supplied (built by
    :func:`build_question_answer_family_index`), a stale ``QUESTION`` override
    is also cleared once a same-family continuation proves the question was
    answered — even when the loaded row's own status (e.g. a loader-derived
    ``QUESTION`` on a historical artifact) would otherwise keep it.
    """
    if agent.status in DISMISSABLE_STATUSES:
        return True
    if override in PENDING_PLAN_REVIEW_STATUS_SET and (
        agent.status in _PENDING_PLAN_OVERRIDE_PROGRESS_STATUSES
        or agent.plan_action in _PENDING_PLAN_OVERRIDE_PROGRESS_ACTIONS
    ):
        return True
    if override in APPROVED_PLAN_STATUSES and agent.status in WORKING_PLAN_STATUSES:
        return True
    if override in ("QUESTION", "ANSWERED"):
        if agent.status in _QUESTION_OVERRIDE_PROGRESS_STATUSES:
            return True
        # A QUESTION override yields to a freshly loaded ANSWERED row (the
        # user's response reached disk). The reverse must NOT clear: an
        # optimistic ANSWERED override survives a loader-produced QUESTION row
        # until the runner consumes the response and the marker clears.
        if override == "QUESTION" and agent.status == "ANSWERED":
            return True
    if question_answer_family_index is not None and (
        _question_override_answered_by_family(
            agent, override, question_answer_family_index
        )
    ):
        return True
    return False


def is_axe_spawned_agent(agent: Agent) -> bool:
    """Check if agent was spawned by sase axe (not user-initiated).

    Agents spawned by axe should not trigger notifications since they're
    automated background tasks.

    Args:
        agent: The agent to check.

    Returns:
        True if agent was spawned by axe, False if user-initiated.
    """
    if agent.workflow:
        # Normalize hyphens to underscores (canonical form uses underscores,
        # e.g. xprompt workflow_label "fix_hook")
        workflow = agent.workflow.replace("-", "_")
        # axe-spawned workflows start with axe(...)
        if workflow.startswith(("axe(mentor)", "axe(fix_hook)", "axe(crs)", "mentor(")):
            return True
        # Plain workflow names for axe-spawned types (from workflow_state.json or Patch)
        if workflow in ("fix_hook", "crs", "mentor", "summarize_hook"):
            return True

    return False


def load_agents_from_disk_with_state(
    dismissed_agents: set[tuple[AgentType, str, str | None]],
    *,
    patch_snapshot: list[Patch] | None = None,
    changespec_snapshot: list[Patch] | None = None,  # legacy compatibility alias
    full_history: bool = False,
    use_artifact_index: bool = True,
    source: str = "unknown",
) -> _AgentDiskLoadResult:
    """Load agents from disk and include the tiered load state."""

    from ....dismissed_agents import dismissed_bundle_identities_snapshot

    if patch_snapshot is None:
        patch_snapshot = changespec_snapshot  # legacy compatibility alias

    with tui_trace(
        "agents.load_from_disk",
        source=source or "unknown",
        full_history=full_history,
    ) as counters:
        dismissed_bundle_identities = dismissed_bundle_identities_snapshot()
        result = _load_agents_from_disk_impl(
            dismissed_agents,
            dismissed_bundle_identities,
            patch_snapshot=patch_snapshot,
            full_history=full_history,
            use_artifact_index=use_artifact_index,
        )
        state = result.load_state
        counters["data_cost"] = classify_agents_data_cost(
            full_history=full_history,
            load_state=state,
        )
        counters["tier"] = state.tier
        counters["artifact_source"] = state.artifact_source
        counters["complete_history"] = state.complete_history
        counters["complete_visible_inbox"] = state.complete_visible_inbox
        counters["repair_recommended"] = state.repair_recommended
        counters["repair_reason"] = state.repair_reason
        counters["truncated"] = state.truncated
        counters["used_artifact_index"] = state.used_artifact_index
        counters["index_error"] = state.index_error
        return result


def load_agent_artifact_delta_from_disk_with_state(
    dismissed_agents: set[tuple[AgentType, str, str | None]],
    artifact_dirs: Sequence[Path | str],
    *,
    patch_snapshot: list[Patch] | None = None,
    changespec_snapshot: list[Patch] | None = None,  # legacy compatibility alias
    source: str = "unknown",
    update_index: bool = True,
    deleted_artifact_dirs: Sequence[Path | str] = (),
) -> _AgentDiskLoadResult:
    """Load agents from exact artifact dirs and include the delta load state."""

    from ....dismissed_agents import dismissed_bundle_identities_snapshot

    if patch_snapshot is None:
        patch_snapshot = changespec_snapshot  # legacy compatibility alias

    with tui_trace(
        "agents.load_artifact_delta_from_disk",
        source=source or "unknown",
        artifact_dirs=len(artifact_dirs),
    ) as counters:
        dismissed_bundle_identities = dismissed_bundle_identities_snapshot()
        result = _load_agent_artifact_delta_from_disk_impl(
            dismissed_agents,
            dismissed_bundle_identities,
            artifact_dirs,
            patch_snapshot=patch_snapshot,
            update_index=update_index,
            deleted_artifact_dirs=deleted_artifact_dirs,
        )
        state = result.load_state
        counters["data_cost"] = classify_agents_data_cost(artifact_delta=True)
        counters["tier"] = state.tier
        counters["artifact_source"] = state.artifact_source
        counters["complete_history"] = state.complete_history
        counters["complete_visible_inbox"] = state.complete_visible_inbox
        counters["repair_recommended"] = state.repair_recommended
        counters["repair_reason"] = state.repair_reason
        counters["truncated"] = state.truncated
        counters["used_artifact_index"] = state.used_artifact_index
        counters["index_error"] = state.index_error
        return result


def hydrate_agent_attempt_history(agent: Agent) -> bool:
    """Populate prior-attempt history for one agent on demand.

    The normal Agents-tab refresh path intentionally leaves
    ``agent.attempt_history`` empty so it does not list/stat
    ``artifacts/attempts/<N>/`` for every visible row.  Detail panes,
    attempt-view actions, and content-search workers call this helper when
    they truly need the attempt records.

    Returns ``True`` when the agent's loaded history changed.
    """
    artifacts_dir = agent.get_artifacts_dir()
    if not artifacts_dir:
        return False

    from ._snapshot_cache import get_global_snapshot_cache

    records = get_global_snapshot_cache().attempt_history_for(artifacts_dir)
    if agent.attempt_history == records:
        return False
    agent.attempt_history = records
    return True


def _apply_loaded_agent_disk_projections(
    all_agents: list[Agent],
    dismissed_agents: set[tuple[AgentType, str, str | None]],
    dismissed_bundle_identities: set[tuple[AgentType, str, str | None]],
    load_state: AgentLoadState,
) -> _AgentDiskLoadResult:
    # Populate retry fields from retry_state.json for running agents. Runtime
    # liveness provenance keeps family roots eligible even after semantic
    # aggregation mirrors a failed child onto their display status. Prior
    # attempt history is hydrated lazily by selected detail/search paths; doing
    # it here would list/stat artifacts/attempts/<N>/ for every row.
    from sase.ace.agent_tribes import load_agent_tribes

    from ._snapshot_cache import get_global_snapshot_cache

    snapshot_cache = get_global_snapshot_cache()
    tribes_by_identity = load_agent_tribes()

    for agent in all_agents:
        if agent.identity in tribes_by_identity:
            agent.tribe = tribes_by_identity[agent.identity]
        artifacts_dir = agent.get_artifacts_dir()

        if agent.status != "RUNNING" and not agent.runner_is_live:
            continue
        if not artifacts_dir:
            continue
        retry_state = snapshot_cache.retry_state_for(artifacts_dir)
        if retry_state is None:
            continue
        agent.retry_count = retry_state.retry_count
        agent.max_retries = retry_state.max_retries
        agent.retry_next_at_epoch = retry_state.next_retry_at_epoch
        agent.retry_wait_seconds = retry_state.wait_seconds
        agent.using_fallback = retry_state.using_fallback
        agent.fallback_model = retry_state.fallback_model
        agent.retry_status = retry_state.status
        if retry_state.status == "retrying":
            agent.status = "RETRYING"

    effective_dismissed = dismissed_agents | dismissed_bundle_identities

    # Build secondary index for robust dismissed matching
    dismissed_suffixes: set[str] = {
        raw_suffix for _, _, raw_suffix in effective_dismissed if raw_suffix is not None
    }

    # Capture dismissed agents found by the loader (for revive + self-healing).
    # Exclude live agents: a done.json auto-dismiss can share the same
    # identity/raw_suffix as a still-active runner; treating the live row as
    # dismissed would delete its artifacts and hide it. Display status is not
    # sufficient because retrying family roots can temporarily mirror FAILED.
    dismissed_from_loader = [
        a
        for a in all_agents
        if a.status != "RUNNING"
        and not a.runner_is_live
        and (
            a.identity in effective_dismissed
            or (a.raw_suffix is not None and a.raw_suffix in dismissed_suffixes)
        )
    ]

    return _AgentDiskLoadResult(
        all_agents=all_agents,
        dismissed_from_loader=dismissed_from_loader,
        load_state=load_state,
        dismissed_bundle_identities=dismissed_bundle_identities,
    )


def _load_agents_from_disk_impl(
    dismissed_agents: set[tuple[AgentType, str, str | None]],
    dismissed_bundle_identities: set[tuple[AgentType, str, str | None]],
    *,
    patch_snapshot: list[Patch] | None = None,
    full_history: bool = False,
    use_artifact_index: bool = True,
) -> _AgentDiskLoadResult:
    from ...models.agent_loader import load_tiered_agents

    all_agents, load_state = load_tiered_agents(
        patch_snapshot=patch_snapshot,
        full_history=full_history,
        use_artifact_index=use_artifact_index,
    )
    return _apply_loaded_agent_disk_projections(
        all_agents,
        dismissed_agents,
        dismissed_bundle_identities,
        load_state,
    )


def _load_agent_artifact_delta_from_disk_impl(
    dismissed_agents: set[tuple[AgentType, str, str | None]],
    dismissed_bundle_identities: set[tuple[AgentType, str, str | None]],
    artifact_dirs: Sequence[Path | str],
    *,
    patch_snapshot: list[Patch] | None = None,
    update_index: bool = True,
    deleted_artifact_dirs: Sequence[Path | str] = (),
) -> _AgentDiskLoadResult:
    from ...models.agent_loader import load_artifact_delta_agents

    all_agents, load_state = load_artifact_delta_agents(
        artifact_dirs,
        patch_snapshot=patch_snapshot,
        update_index=update_index,
        deleted_artifact_dirs=deleted_artifact_dirs,
    )
    return _apply_loaded_agent_disk_projections(
        all_agents,
        dismissed_agents,
        dismissed_bundle_identities,
        load_state=load_state,
    )
