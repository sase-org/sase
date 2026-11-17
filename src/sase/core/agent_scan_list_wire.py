"""Compact list wire records for the agent/artifact snapshot scan.

Split out of :mod:`sase.core.agent_scan_wire` to keep each module under the
500-line cap. These are the Python mirror of the additive
``AgentArtifactList*`` contract in ``sase-core``
(``crates/sase_core/src/agent_scan/list/wire.rs``): scalar list facts plus
small typed sequences, with detail-only payloads (tracebacks, raw prompts,
large outputs, linked repositories, media lists, instruction manifests)
deferred to selected-record hydration.

Field names differ from the full record on purpose (``meta`` versus
``agent_meta``, ``workflow`` versus ``workflow_state``,
``record_shape="compact"``) so a compact payload can never be mistaken for
a nested full record. ``None`` serializes as JSON ``null``; empty lists
serialize as ``[]``; marker presence is preserved (``None`` means the
marker was absent).

Shared summary types already used by the full contract are reused here
instead of redefined: :class:`AgentArtifactScanOptionsWire`,
:class:`AgentArtifactScanStatsWire`,
:class:`AgentArtifactIndexWindowWire`,
:class:`AgentArtifactIndexCompletenessWire`,
:class:`AgentClanContextWire`, :class:`CreatedEpicWire`,
:class:`WaitEpicFollowEntryWire`, :class:`WaitTurnBindingWire`,
:class:`AgentSessionTurnWire`, and :class:`FinalizerStatusSummaryWire`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sase.core.agent_scan_wire_agent_session_turn import AgentSessionTurnWire
from sase.core.agent_scan_wire_markers_epic import (
    CreatedEpicWire,
    WaitEpicFollowEntryWire,
)
from sase.core.agent_scan_wire_markers_finalizer import FinalizerStatusSummaryWire
from sase.core.agent_scan_wire_markers_wait_turn import WaitTurnBindingWire
from sase.core.agent_scan_wire_records import (
    AgentArtifactIndexCompletenessWire,
    AgentArtifactIndexWindowWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentClanContextWire,
)

#: Schema version for the additive compact list snapshot. Bumped only on
#: incompatible changes to the compact shape; checked by the list decoder.
AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION = 1

#: Payload shape discriminator for a compact list record.
AgentArtifactListRecordShape = Literal["compact"]


@dataclass(frozen=True)
class AgentArtifactListOutputFactsWire:
    """List-time facts extracted from a step or done output map.

    Only ``meta_*`` keys and ``diff_path`` survive. ``_raw``, ``_data``,
    and every other detail payload are dropped by the projection.
    """

    meta: dict[str, Any] = field(default_factory=dict)
    diff_path: str | None = None


@dataclass(frozen=True)
class AgentArtifactListRecoveryWire:
    """Compact recovery facts used by list restart and hijack chips."""

    state: str | None = None
    reason: str | None = None
    reason_text: str | None = None
    requested_at: str | None = None
    updated_at: str | None = None
    episode_id: str | None = None
    hijack_id: str | None = None


@dataclass(frozen=True)
class AgentArtifactListMetaWire:
    """Compact projection of ``agent_meta.json`` for list paint and filters.

    Deferred (full-record-only) fields: linked repositories, output
    variables, status-bucket override, instruction-bundle files, and the
    identity/scheduling details listed in the phase field inventory.
    """

    name: str | None = None
    cl_name: str | None = None
    process_identity: str | None = None
    runner_claim_owner_key: str | None = None
    pid: int | None = None
    model: str | None = None
    llm_provider: str | None = None
    reasoning_effort: str | None = None
    model_alias: str | None = None
    vcs_provider: str | None = None
    workspace_dir: str | None = None
    workspace_num: int | None = None
    plan_path: str | None = None
    sdd_plan_path: str | None = None
    epic_plan_ref: str | None = None
    plan: bool = False
    plan_approved: bool = False
    plan_action: str | None = None
    plan_committed: bool | None = None
    plan_submitted_at: list[str] = field(default_factory=list)
    epic_bead_id: str | None = None
    phase_bead_id: str | None = None
    created_epics: list[CreatedEpicWire] = field(default_factory=list)
    commit_diff_path: str | None = None
    tribe: str | None = None
    agent_tab: str | None = None
    wait_for: list[str] = field(default_factory=list)
    wait_for_beads: list[str] = field(default_factory=list)
    wait_for_hoods: list[str] = field(default_factory=list)
    wait_for_epics_of: list[str] = field(default_factory=list)
    wait_epic_follows: list[WaitEpicFollowEntryWire] = field(default_factory=list)
    wait_turn_bindings: list[WaitTurnBindingWire] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None
    queue_capacity: int | None = None
    queue_capacity_explicit: bool = False
    queue_capacity_multiplier: float | None = None
    wait_priority: int | None = None
    queue_weight: float | None = None
    queue_weight_explicit: bool = False
    queue_weight_invalid: bool = False
    queue_weight_error: str | None = None
    approve: bool = False
    auto_approve_plan_action: str | None = None
    auto_approve_argument: str | None = None
    hidden: bool = False
    role_suffix: str | None = None
    agent_session: str | None = None
    agent_session_role: str | None = None
    agent_session_parallel: bool = False
    plan_chain_root: bool = False
    agent_clan: str | None = None
    agent_clan_generation: str | None = None
    clan_tribe: str | None = None
    clan_summary: str | None = None
    parent_timestamp: str | None = None
    retry_of_timestamp: str | None = None
    retry_attempt: int | None = None
    retry_chain_root_timestamp: str | None = None
    retried_as_timestamp: str | None = None
    retry_terminal: bool = False
    retry_error_category: str | None = None
    retry_started_at: list[str] = field(default_factory=list)
    epic_started_at: str | None = None
    feedback_submitted_at: list[str] = field(default_factory=list)
    questions_submitted_at: list[str] = field(default_factory=list)
    run_started_at: str | None = None
    stopped_at: str | None = None
    wait_completed_at: str | None = None
    question_request_path: str | None = None
    question_response_path: str | None = None
    question_session_id: str | None = None
    imported_source_owner: dict[str, Any] | None = None
    source_machine: str | None = None
    output_path: str | None = None
    finalizer_status: FinalizerStatusSummaryWire | None = None
    auto_restart: dict[str, Any] | None = None
    agent_session_turn: AgentSessionTurnWire | None = None


@dataclass(frozen=True)
class AgentArtifactListDoneWire:
    """Compact done-marker facts for list paint and status overrides."""

    outcome: str | None = None
    cl_name: str | None = None
    project_file: str | None = None
    workspace_num: int | None = None
    workspace_dir: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    vcs_provider: str | None = None
    name: str | None = None
    plan_path: str | None = None
    diff_path: str | None = None
    step_output: AgentArtifactListOutputFactsWire | None = None
    error: str | None = None
    retried_as_timestamp: str | None = None
    retry_chain_root_timestamp: str | None = None
    retry_error_category: str | None = None
    approve: bool = False
    hidden: bool = False
    repeat_stopped: bool = False
    status_label: str | None = None
    imported_source_owner: dict[str, Any] | None = None
    source_machine: str | None = None
    recovery: AgentArtifactListRecoveryWire | None = None
    agent_session_turn: AgentSessionTurnWire | None = None


@dataclass(frozen=True)
class AgentArtifactListRunningWire:
    """Compact running-marker facts; presence marks a home running row."""

    pid: int | None = None
    process_identity: str | None = None
    cl_name: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    vcs_provider: str | None = None
    workspace_dir: str | None = None


@dataclass(frozen=True)
class AgentArtifactListWaitingWire:
    """Compact waiting-marker facts.

    Presence on STARTING/RUNNING forces WAITING even when wait lists are
    empty. Held-by/hold-expiry facts stay deferred (filesystem overlay).
    """

    waiting_for: list[str] = field(default_factory=list)
    wait_for_beads: list[str] = field(default_factory=list)
    wait_for_hoods: list[str] = field(default_factory=list)
    wait_for_epics_of: list[str] = field(default_factory=list)
    wait_epic_follows: list[WaitEpicFollowEntryWire] = field(default_factory=list)
    wait_turn_bindings: list[WaitTurnBindingWire] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None
    queue_capacity: int | None = None
    queue_capacity_multiplier: float | None = None
    queue_capacity_explicit: bool = False
    wait_priority: int | None = None
    wait_priority_explicit: bool | None = None
    queue_weight: float | None = None
    queue_weight_explicit: bool = False
    queue_weight_invalid: bool = False
    queue_weight_error: str | None = None
    slot_requested_at: str | None = None


@dataclass(frozen=True)
class AgentArtifactListPendingQuestionWire:
    """Compact pending-question marker; presence yields the runner slot."""

    session_id: str | None = None
    request_path: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True)
class AgentArtifactListWorkflowStepWire:
    """Compact workflow-state step used by parent merge and child status."""

    name: str = ""
    status: str = ""
    output: AgentArtifactListOutputFactsWire | None = None
    error: str | None = None


@dataclass(frozen=True)
class AgentArtifactListWorkflowWire:
    """Compact workflow parent facts; presence marks a workflow parent row."""

    workflow_name: str = ""
    cl_name: str | None = None
    status: str = ""
    pid: int | None = None
    appears_as_agent: bool = False
    is_anonymous: bool = False
    hidden: bool = False
    current_step_index: int = 0
    start_time: str | None = None
    error: str | None = None
    activity: str | None = None
    steps: list[AgentArtifactListWorkflowStepWire] = field(default_factory=list)


@dataclass(frozen=True)
class AgentArtifactListStepWire:
    """Compact prompt-step child facts."""

    file_name: str = ""
    workflow_name: str = ""
    step_name: str = ""
    step_type: str = ""
    step_source: str | None = None
    step_index: int | None = None
    total_steps: int | None = None
    parent_step_index: int | None = None
    parent_total_steps: int | None = None
    status: str = ""
    hidden: bool = False
    is_pre_prompt_step: bool = False
    embedded_workflow_name: str | None = None
    artifacts_dir: str | None = None
    diff_path: str | None = None
    error: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    reasoning_effort: str | None = None
    model_alias: str | None = None
    output: AgentArtifactListOutputFactsWire | None = None


@dataclass(frozen=True)
class AgentArtifactListRecordWire:
    """One compact artifact row for TUI list construction.

    ``plan_path`` is the flattened ``plan_path.json`` marker value.
    """

    project_name: str
    project_dir: str
    project_file: str
    workflow_dir_name: str
    artifact_dir: str
    timestamp: str
    has_done_marker: bool = False
    record_shape: AgentArtifactListRecordShape = "compact"
    meta: AgentArtifactListMetaWire | None = None
    done: AgentArtifactListDoneWire | None = None
    running: AgentArtifactListRunningWire | None = None
    waiting: AgentArtifactListWaitingWire | None = None
    pending_question: AgentArtifactListPendingQuestionWire | None = None
    workflow: AgentArtifactListWorkflowWire | None = None
    plan_path: str | None = None
    prompt_steps: list[AgentArtifactListStepWire] = field(default_factory=list)


@dataclass(frozen=True)
class AgentArtifactListSnapshotWire:
    """Compact snapshot returned by list index queries and source scans."""

    schema_version: int
    projects_root: str
    options: AgentArtifactScanOptionsWire
    stats: AgentArtifactScanStatsWire
    index_window: AgentArtifactIndexWindowWire | None = None
    records: list[AgentArtifactListRecordWire] = field(default_factory=list)
    clan_context: list[AgentClanContextWire] = field(default_factory=list)
    index_completeness: AgentArtifactIndexCompletenessWire | None = None


__all__ = [
    "AGENT_ARTIFACT_LIST_WIRE_SCHEMA_VERSION",
    "AgentArtifactListDoneWire",
    "AgentArtifactListMetaWire",
    "AgentArtifactListOutputFactsWire",
    "AgentArtifactListPendingQuestionWire",
    "AgentArtifactListRecordShape",
    "AgentArtifactListRecordWire",
    "AgentArtifactListRecoveryWire",
    "AgentArtifactListRunningWire",
    "AgentArtifactListSnapshotWire",
    "AgentArtifactListStepWire",
    "AgentArtifactListWaitingWire",
    "AgentArtifactListWorkflowStepWire",
    "AgentArtifactListWorkflowWire",
]
