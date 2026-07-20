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
        cl_name: ChangeSpec name recorded at completion.
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
    """

    outcome: str | None = None
    finished_at: float | None = None
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
    repeat_stopped: bool = False
    stopped_by: str | None = None


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
    commit_changespec_name: str | None = None
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
    agent_family: str | None = None
    agent_family_role: str | None = None
    agent_family_parallel: bool = False
    plan_chain_root: bool = False
    tribe: str | None = None
    output_variables: dict[str, str] = field(default_factory=dict)
    output_path: str | None = None
    pid: int | None = None
    model: str | None = None
    llm_provider: str | None = None
    reasoning_effort: str | None = None
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
    wait_duration: float | None = None
    wait_until: str | None = None
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


@dataclass(frozen=True)
class RunningMarkerWire:
    """Compact projection of ``running.json`` (home-mode running marker).

    Home-mode agents (``projects/home/...``) record liveness here instead
    of via the project ``.gp`` RUNNING field. The wire keeps only the
    fields the TUI loader and CLI listing actually consume.
    """

    pid: int | None = None
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

    waiting_for: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None
    wait_runners: int | None = None
    wait_runners_explicit: bool = False
    slot_requested_at: str | None = None


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
    output: dict[str, Any] | None = None
    output_types: dict[str, str] | None = None


@dataclass(frozen=True)
class PlanPathMarkerWire:
    """Compact projection of ``plan_path.json``.

    The TUI workflow loader reads the ``plan_path`` field to surface a
    plan link on the WORKFLOW-typed agent.
    """

    plan_path: str | None = None


__all__ = [
    "AgentMetaWire",
    "DoneMarkerWire",
    "PendingQuestionMarkerWire",
    "PlanPathMarkerWire",
    "PromptStepMarkerWire",
    "RunningMarkerWire",
    "WaitingMarkerWire",
    "WorkflowStateWire",
    "WorkflowStepStateWire",
]
