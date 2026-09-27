"""Marker-file wire dataclasses for the agent/artifact scan facade.

Split out of :mod:`sase.core.agent_scan_wire` to keep each module under the
500-line cap. The marker wires are the per-file projections of the small JSON
markers that live inside an artifact directory (``done.json``,
``agent_meta.json``, ``running.json``, etc.). The top-level scan/record wires
and the conversion helpers live in sibling modules.

See :mod:`sase.core.agent_scan_wire` for the schema-version contract and the
overall scope of the snapshot scan boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.core.agent_scan_wire_agent_session_turn import AgentSessionTurnWire

#: Maximum characters kept for any ``finalizer_status`` string (plan §3.3 C5).
FINALIZER_STATUS_STR_CAP = 120

#: Maximum per-run instance entries kept on the scan wire (plan §3.3 C5).
FINALIZER_STATUS_MAX_INSTANCES = 16


@dataclass(frozen=True)
class FinalizerStatusRunnerWire:
    """Runner that executed the finalizer phase (plan §3.3 C5)."""

    pid: int | None = None
    identity: str | None = None


@dataclass(frozen=True)
class FinalizerStatusInstanceWire:
    """One finalizer instance entry of the row summary (plan §3.3 C5)."""

    id: str = ""
    status: str | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    op: str | None = None
    step: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    headline: str | None = None
    warnings: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class FinalizerStatusSummaryWire:
    """Tolerant row summary of finalizer execution (plan §3.3 C5)."""

    schema_version: int | None = None
    phase: str | None = None
    reason: str | None = None
    status: str | None = None
    plan_digest: str | None = None
    run_id: str | None = None
    started_at: float | None = None
    updated_at: float | None = None
    runner: FinalizerStatusRunnerWire | None = None
    instances: list[FinalizerStatusInstanceWire] = field(default_factory=list)
    instance_count: int | None = None


def _capped_status_str(value: object) -> str | None:
    """Return *value* capped to the C5 string ceiling, or None when not a str."""
    if not isinstance(value, str):
        return None
    if len(value) <= FINALIZER_STATUS_STR_CAP:
        return value
    return value[:FINALIZER_STATUS_STR_CAP]


def _status_int(value: object) -> int | None:
    """Return *value* as a non-negative int, or None when unusable.

    Bools, negative numbers, NaN/infinite floats, and non-numeric values are
    dropped, mirroring the Rust scanner's lenient coercion.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        if value < 0 or not value.is_integer():
            return None
        return int(value)
    return None


def _status_float(value: object) -> float | None:
    """Return *value* as a non-negative finite float, or None when unusable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return number if number >= 0 else None
    return None


def finalizer_status_from_mapping(
    data: object,
) -> FinalizerStatusSummaryWire | None:
    """Coerce a raw ``finalizer_status`` mapping leniently (plan §3.3 C5).

    A non-mapping value, or a missing or empty ``phase`` string, gives None.
    Strings are capped at 120 characters, at most 16 instances are kept,
    entries without a string ``id`` are dropped, negative/NaN/non-numeric
    numbers are dropped, and unknown keys are ignored. A malformed summary
    never raises. Mirrors the Rust scanner's ``finalizer_status_from_value``.
    """
    if not isinstance(data, dict):
        return None
    phase = _capped_status_str(data.get("phase"))
    if not phase:
        return None
    raw_instances = data.get("instances")
    instances: list[FinalizerStatusInstanceWire] = []
    if isinstance(raw_instances, list):
        for entry in raw_instances:
            if not isinstance(entry, dict):
                continue
            entry_id = _capped_status_str(entry.get("id"))
            if not entry_id:
                continue
            instances.append(
                FinalizerStatusInstanceWire(
                    id=entry_id,
                    status=_capped_status_str(entry.get("status")),
                    attempt=_status_int(entry.get("attempt")),
                    max_attempts=_status_int(entry.get("max_attempts")),
                    op=_capped_status_str(entry.get("op")),
                    step=_capped_status_str(entry.get("step")),
                    started_at=_status_float(entry.get("started_at")),
                    finished_at=_status_float(entry.get("finished_at")),
                    headline=_capped_status_str(entry.get("headline")),
                    warnings=_status_int(entry.get("warnings")),
                    reason=_capped_status_str(entry.get("reason")),
                )
            )
            if len(instances) >= FINALIZER_STATUS_MAX_INSTANCES:
                break
    raw_runner = data.get("runner")
    runner: FinalizerStatusRunnerWire | None = None
    if isinstance(raw_runner, dict):
        runner = FinalizerStatusRunnerWire(
            pid=_status_int(raw_runner.get("pid")),
            identity=_capped_status_str(raw_runner.get("identity")),
        )
    return FinalizerStatusSummaryWire(
        schema_version=_status_int(data.get("schema_version")),
        phase=phase,
        reason=_capped_status_str(data.get("reason")),
        status=_capped_status_str(data.get("status")),
        plan_digest=_capped_status_str(data.get("plan_digest")),
        run_id=_capped_status_str(data.get("run_id")),
        started_at=_status_float(data.get("started_at")),
        updated_at=_status_float(data.get("updated_at")),
        runner=runner,
        instances=instances,
        instance_count=_status_int(data.get("instance_count")),
    )


@dataclass(frozen=True)
class DoneMarkerWire:
    """Compact projection of ``done.json`` (one per finished agent).

    Attributes:
        outcome: ``"completed"`` / ``"failed"`` / ``"plan_rejected"`` /
            ``"epic_approved"`` / ``"epic_launch_failed"`` / ``"stopped"`` /
            ``"noop"``. ``None`` when the marker omits the field.
        finished_at: Unix epoch seconds. Float because some writers emit
            fractional seconds. ``None`` when the field is missing or
            non-numeric.
        patch_name: Patch name recorded at completion.
        cl_name: Legacy ChangeSpec/branch name recorded at completion.
        project_file: Absolute path to the project ``.gp`` file.
        workspace_num: Workspace number released on completion.
        workspace_dir: Resolved directory the agent ran in, when recorded.
        pid: PID of the agent process at completion (informational).
        model: Last LLM model recorded.
        llm_provider: Last LLM provider recorded.
        vcs_provider: VCS provider recorded.
        name: Agent name set via ``%id`` or TUI rename.
        plan_path: Path to a plan written by the agent (if any).
        diff_path: Path to a diff produced by the agent (if any).
        markdown_pdf_paths: Generated PDFs for Markdown files added or modified
            by the agent.
        image_paths: Image files added or modified by the agent.
        video_paths: Video files added or modified by the agent.
        response_path: Path to the agent response transcript.
        output_path: Path to a per-agent log/output file.
        step_output: Last step's output dict, when the agent was a
            workflow step. JSON-safe leaves only.
        error: Error message recorded for failed agents.
        traceback: Traceback recorded for failed agents.
        retried_as_timestamp: Forward pointer to the spawn-on-retry child.
        retry_chain_root_timestamp: Root of a retry chain.
        retry_error_category: Category that triggered the retry.
        approve: Auto-approve flag from launch options.
        hidden: Hidden-from-TUI flag from launch options.
        repeat_stopped: ``True`` for a repeat-chain slot that a predecessor's
            ``STOP`` output variable skipped. The marker keeps
            ``outcome: "completed"`` so ``%wait`` resolution still cascades,
            but the TUI surfaces a distinct ``STOPPED`` status.
        stopped_by: Name of the chain predecessor that set ``STOP``, when
            recorded.
        imported_transaction_key: Project-scoped journal key used to keep
            transactional imports hidden until their whole hood is complete.
        status_label: The configured stop-status label to display
            (e.g. ``MONITORED``), overriding the raw ``outcome``.
        agent_session_turn: Terminal monitor or gate-turn projection, folding the
            marker's flat ``monitor_*`` / ``gate_*`` fields (mirroring the
            running member's ``agent_meta.json::agent_session_turn``). ``None``
            when the record is neither.
    """

    outcome: str | None = None
    finished_at: float | None = None
    patch_name: str | None = None
    cl_name: str | None = None
    project_file: str | None = None
    workspace_num: int | None = None
    workspace_dir: str | None = None
    pid: int | None = None
    model: str | None = None
    llm_provider: str | None = None
    vcs_provider: str | None = None
    name: str | None = None
    plan_path: str | None = None
    diff_path: str | None = None
    markdown_pdf_paths: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    video_paths: list[str] = field(default_factory=list)
    response_path: str | None = None
    output_path: str | None = None
    step_output: dict[str, Any] | None = None
    error: str | None = None
    traceback: str | None = None
    retried_as_timestamp: str | None = None
    retry_chain_root_timestamp: str | None = None
    retry_error_category: str | None = None
    approve: bool = False
    hidden: bool = False
    status_bucket: str | None = None
    repeat_stopped: bool = False
    stopped_by: str | None = None
    imported_transaction_key: str | None = None
    source_machine: str | None = None
    imported_source_owner: dict[str, Any] | None = None
    status_label: str | None = None
    agent_session_turn: AgentSessionTurnWire | None = None
    monitor_diagnostic_manifest_ref: str | None = None
    monitor_retained_log_ref: str | None = None
    continuation_monitor_result_id: str | None = None
    continuation_monitor_result_ref: str | None = None
    continuation_checkpoint_ref: str | None = None
    continuation_node_ref: str | None = None
    continuation_manifest_ref: str | None = None
    continuation_budget_decision_path: str | None = None
    monitor_followup_budget_decision_path: str | None = None

    @property
    def agent_session_shell(self) -> AgentSessionTurnWire | None:
        """Deprecated alias for :attr:`agent_session_turn` (legacy sase-shell spelling)."""

        return self.agent_session_turn


@dataclass(frozen=True)
class AgentMetaWire:
    """Compact projection of ``agent_meta.json``.

    Carries the identity, scheduling, and retry-lineage fields that
    ``enrich_agent_from_meta`` and ``find_named_agent`` consult. Field
    docstrings on the source dataclasses (``Agent`` / ``RunningAgentInfo``)
    are the canonical reference for semantics.
    """

    name: str | None = None
    artifact_agent_id: str | None = None
    artifact_source_dir: str | None = None
    patch_name: str | None = None
    changespec_name: str | None = None
    cl_name: str | None = None
    bead_id: str | None = None
    plan_path: str | None = None
    sdd_prompt_path: str | None = None
    sdd_plan_path: str | None = None
    epic_plan_ref: str | None = None
    question_request_path: str | None = None
    question_response_path: str | None = None
    question_session_id: str | None = None
    epic_bead_id: str | None = None
    phase_bead_id: str | None = None
    commit_patch_name: str | None = None
    commit_changespec_name: str | None = None
    stitch_id: str | None = None
    commit_entry_id: str | None = None
    commit_result: str | None = None
    commit_diff_path: str | None = None
    parent_agent_timestamp: str | None = None
    parent_agent_name: str | None = None
    workflow_name: str | None = None
    agent_clan: str | None = None
    agent_clan_generation: str | None = None
    clan_tribe: str | None = None
    clan_summary: str | None = None
    agent_session: str | None = None
    agent_session_role: str | None = None
    agent_session_parallel: bool = False
    source_machine: str | None = None
    imported_source_owner: dict[str, Any] | None = None
    plan_chain_root: bool = False
    tribe: str | None = None
    output_variables: dict[str, Any] = field(default_factory=dict)
    output_path: str | None = None
    pid: int | None = None
    process_identity: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    reasoning_effort: str | None = None
    model_alias: str | None = None
    model_alias_trail: list[str] = field(default_factory=list)
    model_alias_origin: str | None = None
    vcs_provider: str | None = None
    role_suffix: str | None = None
    parent_timestamp: str | None = None
    workspace_num: int | None = None
    workspace_dir: str | None = None
    linked_repos: list[dict[str, Any]] = field(default_factory=list)
    approve: bool = False
    auto_approve_plan_action: str | None = None
    hidden: bool = False
    plan: bool = False
    plan_approved: bool = False
    plan_action: str | None = None
    plan_committed: bool | None = None
    wait_for: list[str] = field(default_factory=list)
    wait_for_beads: list[str] = field(default_factory=list)
    wait_for_hoods: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None
    queue_capacity: int | None = None
    queue_capacity_multiplier: float | None = None
    queue_capacity_explicit: bool = False
    wait_runners: int | None = None
    wait_runners_explicit: bool = False
    wait_priority: int | None = None
    queue_weight: float | None = None
    queue_weight_explicit: bool = False
    queue_weight_invalid: bool = False
    queue_weight_error: str | None = None
    runner_claim_owner_key: str | None = None
    wait_completed_at: str | None = None
    plan_submitted_at: list[str] = field(default_factory=list)
    epic_started_at: str | None = None
    feedback_submitted_at: list[str] = field(default_factory=list)
    questions_submitted_at: list[str] = field(default_factory=list)
    retry_started_at: list[str] = field(default_factory=list)
    run_started_at: str | None = None
    stopped_at: str | None = None
    retry_of_timestamp: str | None = None
    retry_attempt: int | None = None
    retry_chain_root_timestamp: str | None = None
    retried_as_timestamp: str | None = None
    retry_terminal: bool = False
    retry_error_category: str | None = None
    status_bucket: str | None = None
    agent_session_turn: AgentSessionTurnWire | None = None
    monitor_diagnostic_manifest_ref: str | None = None
    monitor_retained_log_ref: str | None = None
    continuation_monitor_result_id: str | None = None
    continuation_monitor_result_ref: str | None = None
    continuation_checkpoint_ref: str | None = None
    continuation_node_ref: str | None = None
    continuation_manifest_ref: str | None = None
    continuation_budget_decision_path: str | None = None
    monitor_followup_budget_decision_path: str | None = None
    turn_kind: str | None = None
    proc_id: str | None = None
    # Tolerant finalizer-execution row summary (plan §3.3 C5). Trailing so
    # existing scan payloads keep their key order; None serializes through
    # the facade but the Rust wire omits it so payloads stay byte-stable.
    finalizer_status: FinalizerStatusSummaryWire | None = None

    @property
    def agent_session_shell(self) -> AgentSessionTurnWire | None:
        """Deprecated alias for :attr:`agent_session_turn` (legacy sase-shell spelling)."""

        return self.agent_session_turn

    @property
    def shell_kind(self) -> str | None:
        """Deprecated alias for :attr:`turn_kind`."""

        return self.turn_kind


@dataclass(frozen=True)
class RunningMarkerWire:
    """Compact projection of ``running.json`` (home-mode running marker).

    Home-mode agents (``projects/home/...``) record liveness here instead
    of via the project ``.gp`` RUNNING field. The wire keeps only the
    fields the TUI loader and CLI listing actually consume.
    """

    pid: int | None = None
    process_identity: str | None = None
    patch_name: str | None = None
    cl_name: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    vcs_provider: str | None = None
    workspace_dir: str | None = None


@dataclass(frozen=True)
class WaitingMarkerWire:
    """Compact projection of ``waiting.json``.

    Overrides ``agent_meta.json`` wait fields when present. The TUI
    loader uses this to flip active pre-run/execution status to ``WAITING``
    and to display an updated wait list edited from the TUI ``w`` keymap.
    """

    patch_name: str | None = None
    cl_name: str | None = None
    waiting_for: list[str] = field(default_factory=list)
    wait_for_beads: list[str] = field(default_factory=list)
    wait_for_hoods: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None
    queue_capacity: int | None = None
    queue_capacity_multiplier: float | None = None
    queue_capacity_explicit: bool = False
    wait_runners: int | None = None
    wait_runners_explicit: bool = False
    wait_priority: int | None = None
    wait_priority_explicit: bool | None = None
    queue_weight: float | None = None
    queue_weight_explicit: bool = False
    queue_weight_invalid: bool = False
    queue_weight_error: str | None = None
    slot_requested_at: str | None = None
    eligible_since: str | None = None
    held_by: str | None = None
    hold_expires_at: float | None = None


@dataclass(frozen=True)
class PendingQuestionMarkerWire:
    """Compact projection of ``pending_question.json``.

    The marker is written by ``handle_questions_flow()`` immediately
    before the response-wait poll loop begins. After a response it remains
    present until the root reacquires a runner slot; kill and exception paths
    remove it during cleanup. Its presence is the authoritative signal that
    the root has yielded capacity, independent of notification state.
    """

    session_id: str | None = None
    request_path: str | None = None
    submitted_at: str | None = None


@dataclass(frozen=True)
class WorkflowStepStateWire:
    """One step entry from ``workflow_state.json``'s ``steps`` array."""

    name: str = ""
    status: str = "pending"
    output: dict[str, Any] | None = None
    output_types: dict[str, str] | None = None
    error: str | None = None
    traceback: str | None = None


@dataclass(frozen=True)
class WorkflowStateWire:
    """Compact projection of ``workflow_state.json``."""

    workflow_name: str = "unknown"
    cl_name: str | None = None
    status: str = "running"
    pid: int | None = None
    appears_as_agent: bool = False
    is_anonymous: bool = False
    hidden: bool = False
    current_step_index: int = 0
    start_time: str | None = None
    error: str | None = None
    traceback: str | None = None
    activity: str | None = None
    pdf_status: dict[str, Any] | None = None
    steps: list[WorkflowStepStateWire] = field(default_factory=list)


@dataclass(frozen=True)
class PromptStepMarkerWire:
    """Compact projection of one ``prompt_step_*.json`` marker.

    Only the fields used by ``load_workflow_agent_steps`` and parent
    workflow enrichment are carried.
    """

    file_name: str
    workflow_name: str = "unknown"
    step_name: str = "unknown"
    step_type: str = "agent"
    step_source: str | None = None
    step_index: int | None = None
    total_steps: int | None = None
    parent_step_index: int | None = None
    parent_total_steps: int | None = None
    status: str = "completed"
    hidden: bool = False
    is_pre_prompt_step: bool = False
    embedded_workflow_name: str | None = None
    artifacts_dir: str | None = None
    diff_path: str | None = None
    response_path: str | None = None
    error: str | None = None
    traceback: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    reasoning_effort: str | None = None
    model_alias: str | None = None
    model_alias_trail: list[str] = field(default_factory=list)
    model_alias_origin: str | None = None
    output: dict[str, Any] | None = None
    output_types: dict[str, str] | None = None


@dataclass(frozen=True)
class PlanPathMarkerWire:
    """Compact projection of ``plan_path.json``.

    The TUI workflow loader reads the ``plan_path`` field to surface a
    plan link on the WORKFLOW-typed agent.
    """

    plan_path: str | None = None


@dataclass(frozen=True)
class UsedXPromptWire:
    """Compact projection of one launch-boundary ``xprompts.json`` entry.

    The scanner collapses entries by ``name``, so ``references`` counts how
    many argument variants of that name the launch prompt referenced. The
    XPrompt statistics rollup aggregates these in Rust; Python mirrors the
    field so scan records round-trip without dropping it.
    """

    name: str
    kind: str = "unknown"
    tags: list[str] = field(default_factory=list)
    references: int = 0


__all__ = [
    "AgentMetaWire",
    "DoneMarkerWire",
    "FinalizerStatusInstanceWire",
    "FinalizerStatusRunnerWire",
    "FinalizerStatusSummaryWire",
    "PendingQuestionMarkerWire",
    "PlanPathMarkerWire",
    "PromptStepMarkerWire",
    "RunningMarkerWire",
    "UsedXPromptWire",
    "WaitingMarkerWire",
    "WorkflowStateWire",
    "WorkflowStepStateWire",
    "finalizer_status_from_mapping",
]
