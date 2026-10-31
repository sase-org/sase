"""Gate and monitor turn metadata from filesystem-backed agent metadata."""

from __future__ import annotations

from sase.monitor_state import is_monitor_member_role
from sase.gate_turn.state import is_real_gate_member

from ._meta_enrichment_gate import apply_gate_meta
from ._meta_enrichment_monitor import apply_monitor_meta
from ..agent import Agent


def apply_filesystem_turn_meta(agent: Agent, data: dict[str, object]) -> None:
    """Project gate and monitor fields from agent metadata."""
    apply_monitor_meta(
        agent,
        monitor_id=data.get("monitor_id"),
        monitor_state=data.get("monitor_state"),
        monitor_command=data.get("monitor_command"),
        monitor_label=data.get("monitor_label"),
        monitor_start_status=data.get("monitor_start_status"),
        monitor_stop_status=data.get("monitor_stop_status"),
        monitor_exit_code=data.get("monitor_exit_code"),
        monitor_supervisor_identity=data.get("monitor_supervisor_identity"),
        monitor_cwd=data.get("monitor_cwd"),
        monitor_reason=data.get("monitor_reason"),
        monitor_next_action=data.get("monitor_next_action"),
        monitor_next_output=data.get("monitor_next_output"),
        monitor_next_model=data.get("monitor_next_model"),
        monitor_completion_ref=data.get("monitor_completion_ref"),
        monitor_profile=data.get("monitor_profile"),
        monitor_policy_digest=data.get("monitor_policy_digest"),
        monitor_timeout_seconds=data.get("monitor_timeout_seconds"),
        monitor_idle_timeout_seconds=data.get("monitor_idle_timeout_seconds"),
        monitor_output_truncated=data.get("monitor_output_truncated"),
        monitor_diagnostic_manifest_ref=data.get("monitor_diagnostic_manifest_ref"),
        monitor_retained_log_ref=data.get("monitor_retained_log_ref"),
        continuation_monitor_result_id=data.get("continuation_monitor_result_id"),
        continuation_monitor_result_ref=data.get("continuation_monitor_result_ref"),
        continuation_checkpoint_ref=data.get("continuation_checkpoint_ref"),
        continuation_node_ref=data.get("continuation_node_ref"),
        continuation_manifest_ref=data.get("continuation_manifest_ref"),
        monitor_budget_decision_path=(
            data.get("continuation_budget_decision_path")
            or data.get("monitor_followup_budget_decision_path")
        ),
        monitor_followup_outcome=data.get("monitor_followup_outcome"),
        monitor_followup_error=data.get("monitor_followup_error"),
        monitor_followup_agent=data.get("monitor_followup_agent"),
        monitor_followup_degraded_reason=data.get("monitor_followup_degraded_reason"),
        monitor_followup_prompt_path=data.get("monitor_followup_prompt_path"),
        monitor_host_completion_status=data.get("monitor_host_completion_status"),
        monitor_host_completion_message=data.get("monitor_host_completion_message"),
        monitor_host_completion_reason=data.get("monitor_host_completion_reason"),
        monitor_member=is_monitor_member_role(
            agent.agent_session_role,
            agent.role_suffix,
        ),
    )
    raw_gate_id = data.get("gate_id")
    apply_gate_meta(
        agent,
        gate_id=data.get("gate_id"),
        gate_kind=data.get("gate_kind"),
        gate_state=data.get("gate_state"),
        gate_start_status=data.get("gate_start_status"),
        gate_stop_status=data.get("gate_stop_status"),
        gate_accent=data.get("gate_accent"),
        gate_output_path=data.get("gate_output_path"),
        gate_output_truncated=data.get("gate_output_truncated"),
        gate_creator_agent=data.get("gate_creator_agent"),
        gate_followup_agent=data.get("gate_followup_agent"),
        gate_next_action=data.get("gate_next_action"),
        gate_next_fork=data.get("gate_next_fork"),
        gate_next_output=data.get("gate_next_output"),
        gate_next_model=data.get("gate_next_model"),
        gate_followup_outcome=data.get("gate_followup_outcome"),
        gate_followup_error=data.get("gate_followup_error"),
        gate_followup_degraded_reason=data.get("gate_followup_degraded_reason"),
        gate_followup_prompt_path=data.get("gate_followup_prompt_path"),
        gate_elapsed_seconds=data.get("gate_elapsed_seconds"),
        gate_label=data.get("gate_label"),
        gate_reason=data.get("gate_reason"),
        gate_timeout_seconds=data.get("gate_timeout_seconds"),
        gate_request_fingerprint=data.get("gate_request_fingerprint"),
        gate_workspace_policy=data.get("gate_workspace_policy"),
        gate_bundle_path=data.get("gate_bundle_path"),
        gate_notification_id=data.get("gate_notification_id"),
        gate_decision_path=data.get("gate_decision_path"),
        gate_member=is_real_gate_member(
            agent.agent_session_role,
            raw_gate_id if isinstance(raw_gate_id, str) else None,
        ),
    )
