"""Presentation-neutral models for rich agent list projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sase.agent.status_buckets import agent_is_asking


_TERMINAL_BUCKETS = {"Done", "Failed"}


@dataclass(frozen=True)
class AgentWaitInfo:
    """Wait metadata projected from agent markers."""

    wait_for: tuple[str, ...] = ()
    wait_duration_seconds: float | None = None
    wait_until: str | None = None
    remaining_seconds: int | None = None
    wait_runners: int | None = None
    wait_runners_explicit: bool = False
    slot_requested_at: str | None = None
    runner_slots_in_use: int | None = None
    runner_slot_queue_position: int | None = None
    runner_slot_queue_size: int | None = None
    runner_slot_holders: tuple[str, ...] = ()

    @property
    def has_wait(self) -> bool:
        return bool(
            self.wait_for
            or self.wait_duration_seconds is not None
            or self.wait_until
            or self.remaining_seconds is not None
            or self.slot_requested_at
        )


@dataclass(frozen=True)
class AgentRetryInfo:
    """Retry lineage metadata projected from agent markers."""

    retry_attempt: int | None = None
    retry_of_timestamp: str | None = None
    retried_as_timestamp: str | None = None
    retry_chain_root_timestamp: str | None = None
    retry_error_category: str | None = None
    fallback_model: str | None = None

    @property
    def has_retry(self) -> bool:
        return bool(
            self.retry_attempt is not None
            or self.retry_of_timestamp
            or self.retried_as_timestamp
            or self.retry_chain_root_timestamp
            or self.retry_error_category
            or self.fallback_model
        )


@dataclass(frozen=True)
class AgentChildrenSummary:
    """Cheap direct-child count summary for folded linear surfaces."""

    count: int = 0
    status_counts: tuple[tuple[str, int], ...] = ()

    @property
    def badge(self) -> str | None:
        return f"×{self.count}" if self.count else None


@dataclass(frozen=True)
class AgentListEntry:
    """Rich, presentation-neutral agent list/detail projection."""

    name: str | None
    project: str
    pid: int | None
    model: str | None
    provider: str | None
    provider_badge: str | None
    workspace_num: int | None
    duration: str
    duration_seconds: int | None
    started_at: datetime | None
    finished_at: datetime | None
    prompt: str | None
    status: str
    status_bucket: str
    status_glyph: str
    approve: bool
    artifacts_dir: str | None
    timestamp: str | None = None
    reasoning_effort: str | None = None
    vcs_provider: str | None = None
    vcs_provider_display: str | None = None
    tribe: str | None = None
    agent_clan: str | None = None
    agent_clan_generation: str | None = None
    clan_tribe: str | None = None
    bead_id: str | None = None
    changespec_name: str | None = None
    cl_name: str | None = None
    workflow_name: str | None = None
    agent_family: str | None = None
    agent_family_role: str | None = None
    parent_agent_name: str | None = None
    plan: bool = False
    plan_approved: bool = False
    plan_action: str | None = None
    auto_approve_plan_action: str | None = None
    pending_question: bool = False
    question_answered: bool = False
    wait: AgentWaitInfo = field(default_factory=AgentWaitInfo)
    retry: AgentRetryInfo = field(default_factory=AgentRetryInfo)
    children: AgentChildrenSummary = field(default_factory=AgentChildrenSummary)
    activity: str | None = None
    output_variables: Mapping[str, str] = field(default_factory=dict)
    artifact_count: int = 0
    commit_count: int = 0
    error: str | None = None
    traceback: str | None = None
    has_file_changes: bool = False
    has_done_marker: bool = False

    @property
    def is_terminal(self) -> bool:
        # Completion and display bucketing are separate concepts. In particular,
        # a completed EPIC APPROVED parent intentionally retains the Running
        # bucket so its handoff state remains visible in history, but it is no
        # longer a live agent and must not appear in active-only integration views.
        return self.has_done_marker or self.status_bucket in _TERMINAL_BUCKETS

    @property
    def needs_user_action(self) -> bool:
        return agent_is_asking(self.status)

    @property
    def auto_badge(self) -> str | None:
        if self.auto_approve_plan_action:
            action = self.auto_approve_plan_action.strip().lower()
            if action == "tale":
                return "⚡T"
            if action == "epic":
                return "⚡E"
        return "⚡" if self.approve else None
