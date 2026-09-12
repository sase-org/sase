"""Gate metadata helpers for agent enrichment."""

from __future__ import annotations

from sase.gate_shell.state import gate_member_status_bucket, gate_state_is_terminal
from sase.gate_shell.status import gate_status_pair

from ..agent import Agent


def apply_gate_meta(
    agent: Agent,
    *,
    gate_id: object,
    gate_kind: object,
    gate_state: object,
    gate_start_status: object,
    gate_stop_status: object,
    gate_accent: object,
    gate_output_path: object = None,
    gate_output_truncated: object = None,
    gate_creator_agent: object = None,
    gate_followup_agent: object = None,
    gate_next_action: object = None,
    gate_next_fork: object = None,
    gate_next_output: object = None,
    gate_next_model: object = None,
    gate_followup_outcome: object = None,
    gate_followup_error: object = None,
    gate_followup_degraded_reason: object = None,
    gate_followup_prompt_path: object = None,
    gate_elapsed_seconds: object = None,
    gate_label: object = None,
    gate_reason: object = None,
    gate_timeout_seconds: object = None,
    gate_request_fingerprint: object = None,
    gate_workspace_policy: object = None,
    gate_bundle_path: object = None,
    gate_notification_id: object = None,
    gate_decision_path: object = None,
    gate_member: bool,
) -> None:
    """Apply gate fields from ``agent_meta.json`` to one row."""
    if not isinstance(gate_id, str) or not gate_id:
        return
    state = gate_state if isinstance(gate_state, str) else "pending"
    pair = gate_status_pair(
        gate_start_status if isinstance(gate_start_status, str) else None,
        gate_stop_status if isinstance(gate_stop_status, str) else None,
    )
    agent.gate_id = gate_id
    agent.gate_kind = gate_kind if isinstance(gate_kind, str) else None
    agent.gate_state = state
    agent.gate_start_status = pair.start
    agent.gate_stop_status = pair.stop
    agent.gate_accent = gate_accent if isinstance(gate_accent, str) else None
    agent.gate_output_path = (
        gate_output_path if isinstance(gate_output_path, str) else None
    )
    agent.gate_output_truncated = bool(gate_output_truncated)
    agent.gate_creator_agent = (
        gate_creator_agent if isinstance(gate_creator_agent, str) else None
    )
    agent.gate_followup_agent = (
        gate_followup_agent if isinstance(gate_followup_agent, str) else None
    )
    agent.gate_next_action = (
        gate_next_action if isinstance(gate_next_action, str) else None
    )
    agent.gate_next_fork = gate_next_fork if isinstance(gate_next_fork, str) else None
    agent.gate_next_output = (
        gate_next_output if isinstance(gate_next_output, str) else None
    )
    agent.gate_next_model = (
        gate_next_model if isinstance(gate_next_model, str) else None
    )
    agent.gate_followup_outcome = (
        gate_followup_outcome if isinstance(gate_followup_outcome, str) else None
    )
    agent.gate_followup_error = (
        gate_followup_error if isinstance(gate_followup_error, str) else None
    )
    agent.gate_followup_degraded_reason = (
        gate_followup_degraded_reason
        if isinstance(gate_followup_degraded_reason, str)
        else None
    )
    agent.gate_followup_prompt_path = (
        gate_followup_prompt_path
        if isinstance(gate_followup_prompt_path, str)
        else None
    )
    if isinstance(gate_elapsed_seconds, (int, float)) and not isinstance(
        gate_elapsed_seconds, bool
    ):
        agent.gate_elapsed_seconds = float(gate_elapsed_seconds)
    agent.gate_label = gate_label if isinstance(gate_label, str) else None
    agent.gate_reason = gate_reason if isinstance(gate_reason, str) else None
    if isinstance(gate_timeout_seconds, (int, float)) and not isinstance(
        gate_timeout_seconds, bool
    ):
        agent.gate_timeout_seconds = float(gate_timeout_seconds)
    agent.gate_request_fingerprint = (
        gate_request_fingerprint if isinstance(gate_request_fingerprint, str) else None
    )
    agent.gate_workspace_policy = (
        gate_workspace_policy if isinstance(gate_workspace_policy, str) else None
    )
    agent.gate_bundle_path = (
        gate_bundle_path if isinstance(gate_bundle_path, str) else None
    )
    agent.gate_notification_id = (
        gate_notification_id if isinstance(gate_notification_id, str) else None
    )
    agent.gate_decision_path = (
        gate_decision_path if isinstance(gate_decision_path, str) else None
    )
    if not gate_member:
        return
    agent.status = pair.stop if gate_state_is_terminal(state) else pair.start
    agent.status_bucket = gate_member_status_bucket(state, agent.status)


def apply_gate_done(
    agent: Agent,
    *,
    gate_id: object = None,
    gate_kind: object = None,
    gate_state: object,
    gate_elapsed_seconds: object = None,
    gate_output_path: object = None,
    gate_output_truncated: object = None,
    gate_bundle_path: object = None,
    gate_notification_id: object = None,
    status_label: object = None,
    gate_followup_outcome: object = None,
    gate_followup_error: object = None,
    gate_followup_degraded_reason: object = None,
    gate_followup_prompt_path: object = None,
) -> None:
    """Apply terminal gate fields from ``done.json`` to one row."""
    if isinstance(gate_id, str) and gate_id:
        agent.gate_id = gate_id
    if isinstance(gate_kind, str) and gate_kind:
        agent.gate_kind = gate_kind
    state = gate_state if isinstance(gate_state, str) else agent.gate_state
    if isinstance(state, str) and state:
        agent.gate_state = state
    if isinstance(gate_elapsed_seconds, (int, float)) and not isinstance(
        gate_elapsed_seconds, bool
    ):
        agent.gate_elapsed_seconds = float(gate_elapsed_seconds)
    if isinstance(gate_output_path, str) and gate_output_path:
        agent.gate_output_path = gate_output_path
    agent.gate_output_truncated = bool(gate_output_truncated)
    if isinstance(gate_bundle_path, str) and gate_bundle_path:
        agent.gate_bundle_path = gate_bundle_path
    if isinstance(gate_notification_id, str) and gate_notification_id:
        agent.gate_notification_id = gate_notification_id
    if isinstance(status_label, str) and status_label:
        pair = gate_status_pair(agent.gate_start_status, status_label)
        agent.gate_start_status = pair.start
        agent.gate_stop_status = pair.stop
        agent.status = pair.stop
    elif agent.gate_stop_status and gate_state_is_terminal(agent.gate_state):
        agent.status = agent.gate_stop_status
    if isinstance(state, str) and state:
        agent.status_bucket = gate_member_status_bucket(agent.gate_state, agent.status)
    if isinstance(gate_followup_outcome, str) and gate_followup_outcome:
        agent.gate_followup_outcome = gate_followup_outcome
    if isinstance(gate_followup_error, str) and gate_followup_error:
        agent.gate_followup_error = gate_followup_error
    if isinstance(gate_followup_degraded_reason, str) and gate_followup_degraded_reason:
        agent.gate_followup_degraded_reason = gate_followup_degraded_reason
    if isinstance(gate_followup_prompt_path, str) and gate_followup_prompt_path:
        agent.gate_followup_prompt_path = gate_followup_prompt_path
