"""Monitor, gate, and proc-shell projections for the Agents tab model."""

from __future__ import annotations

from dataclasses import dataclass, field

from sase.core.agent_scan_wire_markers import FinalizerStatusSummaryWire


@dataclass
class AgentStateOperationsFields:
    """Supervised-command, human-decision, and proc-shell state for one row."""

    # Monitor-member projection. Monitor rows are ordinary agent-session
    # members whose work is one supervised OS command rather than an LLM turn.
    monitor_id: str | None = None
    monitor_state: str | None = None
    monitor_command: str | None = None
    monitor_label: str | None = None
    monitor_start_status: str | None = None
    monitor_stop_status: str | None = None
    monitor_exit_code: int | None = None
    monitor_cwd: str | None = None
    monitor_reason: str | None = None
    monitor_next_action: str | None = None
    monitor_next_output: str | None = None
    monitor_next_model: str | None = None
    monitor_completion_ref: str | None = None
    monitor_profile: str | None = None
    monitor_policy_digest: str | None = None
    monitor_timeout_seconds: float | None = None
    monitor_idle_timeout_seconds: float | None = None
    monitor_output_truncated: bool = False
    monitor_diagnostic_manifest_ref: str | None = None
    monitor_retained_log_ref: str | None = None
    continuation_monitor_result_id: str | None = None
    continuation_monitor_result_ref: str | None = None
    continuation_checkpoint_ref: str | None = None
    continuation_node_ref: str | None = None
    continuation_manifest_ref: str | None = None
    monitor_budget_decision_path: str | None = None

    # Follow-up (``--next``) launch disposition, set once the monitor
    # settles. ``monitor_followup_error`` is the human-readable reason a
    # ``--next`` action was dropped entirely; a degraded launch records no
    # error and is recognizable only by its ``launched-degraded`` outcome.
    # A lane carrying either is stalled and needs a human, not merely
    # finished.
    monitor_followup_outcome: str | None = None
    monitor_followup_error: str | None = None
    monitor_followup_agent: str | None = None
    monitor_followup_degraded_reason: str | None = None
    monitor_followup_prompt_path: str | None = None
    monitor_host_completion_status: str | None = None
    monitor_host_completion_message: str | None = None
    monitor_host_completion_reason: str | None = None

    # Gate-member projection. Gate rows are ordinary agent-session members whose
    # work is a durable human decision rather than an LLM turn.
    gate_id: str | None = None
    gate_kind: str | None = None
    gate_state: str | None = None
    gate_start_status: str | None = None
    gate_stop_status: str | None = None
    gate_accent: str | None = None
    gate_label: str | None = None
    gate_reason: str | None = None
    gate_timeout_seconds: float | None = None
    gate_elapsed_seconds: float | None = None
    gate_output_path: str | None = None
    gate_output_truncated: bool = False
    gate_bundle_path: str | None = None
    gate_notification_id: str | None = None
    gate_decision_path: str | None = None
    gate_creator_agent: str | None = None
    gate_request_fingerprint: str | None = None
    gate_workspace_policy: str | None = None
    gate_execution_active: bool = False
    gate_finalize_proc_id: str | None = None
    gate_next_action: str | None = None
    gate_next_fork: str | None = None
    gate_next_output: str | None = None
    gate_next_model: str | None = None
    gate_followup_agent: str | None = None
    gate_followup_outcome: str | None = None
    gate_followup_error: str | None = None
    gate_followup_degraded_reason: str | None = None
    gate_followup_prompt_path: str | None = None

    # Stand-alone named-proc projection. These rows come from the durable proc
    # store and are presentation-only: they are not SASE agents, do not own
    # artifacts, and must not flow into ordinary agent cleanup/dismiss paths.
    proc_id: str | None = None
    proc_status: str | None = None
    proc_phase: str | None = None
    proc_label: str | None = None
    proc_origin: str | None = None
    proc_language: str | None = None
    proc_code_digest: str | None = None
    proc_safe_preview: str | None = None
    proc_log_path: str | None = None
    proc_log_tail: str = ""
    proc_output_truncated: bool = False
    proc_waits: list[str] = field(default_factory=list)
    proc_condition_result: str | None = None
    proc_supervisor_id: str | None = None
    proc_settlement_state: str | None = None
    proc_request_fingerprint: str | None = None

    # Runner stdout/stderr output file path (for debugging failed agents)
    output_path: str | None = None

    # Tolerant finalizer-execution row summary from
    # ``agent_meta.json["finalizer_status"]`` (plan §3.3 C5). A per-turn hint
    # for glance surfaces; session containers never carry it (they aggregate
    # members in memory), so later readers must not treat a set value as a
    # container aggregate.
    finalizer_status: FinalizerStatusSummaryWire | None = None
