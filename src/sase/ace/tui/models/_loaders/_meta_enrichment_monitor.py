"""Monitor metadata helpers for agent enrichment."""

from __future__ import annotations

from sase.core.staged_handoff import project_monitor_turn_state
from sase.monitor_state import (
    MONITOR_HELD_STATE,
    NOT_ADOPTED_STATUS,
    monitor_state_bucket,
)
from sase.monitor_status import (
    DEFAULT_MONITOR_START_STATUS,
    clamp_monitor_status_or_default,
)

from ..agent import Agent


def _stage_held(value: object) -> bool:
    """Return whether *value* is a truthy ``monitor_stage_held`` flag."""
    if value is True:
        return True
    if type(value) is int:
        return value != 0
    if type(value) is float:
        return value != 0.0
    if isinstance(value, str):
        return bool(value)
    return False


def _projected_monitor_state(
    monitor_state: object,
    stage_held: object = False,
) -> str | None:
    """Project durable monitor facts through the core-held binding."""
    state = monitor_state if isinstance(monitor_state, str) else None
    return project_monitor_turn_state(state, _stage_held(stage_held))


def apply_monitor_meta(
    agent: Agent,
    *,
    monitor_id: object,
    monitor_state: object,
    monitor_command: object,
    monitor_label: object,
    monitor_start_status: object,
    monitor_stop_status: object,
    monitor_exit_code: object,
    monitor_supervisor_identity: object = None,
    monitor_cwd: object = None,
    monitor_reason: object = None,
    monitor_next_action: object = None,
    monitor_next_output: object = None,
    monitor_next_model: object = None,
    monitor_completion_ref: object = None,
    monitor_profile: object = None,
    monitor_policy_digest: object = None,
    monitor_timeout_seconds: object = None,
    monitor_idle_timeout_seconds: object = None,
    monitor_output_truncated: object = None,
    monitor_diagnostic_manifest_ref: object = None,
    monitor_retained_log_ref: object = None,
    continuation_monitor_result_id: object = None,
    continuation_monitor_result_ref: object = None,
    continuation_checkpoint_ref: object = None,
    continuation_node_ref: object = None,
    continuation_manifest_ref: object = None,
    monitor_budget_decision_path: object = None,
    monitor_followup_outcome: object = None,
    monitor_followup_error: object = None,
    monitor_followup_agent: object = None,
    monitor_followup_degraded_reason: object = None,
    monitor_followup_prompt_path: object = None,
    monitor_host_completion_status: object = None,
    monitor_host_completion_message: object = None,
    monitor_host_completion_reason: object = None,
    monitor_member: bool,
    monitor_stage_held: object = False,
) -> None:
    """Apply monitor fields from ``agent_meta.json`` to one row."""
    if not isinstance(monitor_id, str) or not monitor_id:
        return
    state = _projected_monitor_state(monitor_state, monitor_stage_held)
    agent.monitor_id = monitor_id
    agent.monitor_state = state
    agent.monitor_command = (
        monitor_command if isinstance(monitor_command, str) else None
    )
    agent.monitor_label = monitor_label if isinstance(monitor_label, str) else None
    if isinstance(monitor_start_status, str):
        start_status = clamp_monitor_status_or_default(monitor_start_status, default="")
        if start_status:
            agent.monitor_start_status = start_status
    if isinstance(monitor_stop_status, str):
        stop_status = clamp_monitor_status_or_default(monitor_stop_status, default="")
        if stop_status:
            agent.monitor_stop_status = stop_status
    if type(monitor_exit_code) is int:
        agent.monitor_exit_code = monitor_exit_code
    agent.monitor_cwd = monitor_cwd if isinstance(monitor_cwd, str) else None
    agent.monitor_reason = monitor_reason if isinstance(monitor_reason, str) else None
    agent.monitor_next_action = (
        monitor_next_action if isinstance(monitor_next_action, str) else None
    )
    agent.monitor_next_output = (
        monitor_next_output if isinstance(monitor_next_output, str) else None
    )
    agent.monitor_next_model = (
        monitor_next_model if isinstance(monitor_next_model, str) else None
    )
    agent.monitor_completion_ref = (
        monitor_completion_ref if isinstance(monitor_completion_ref, str) else None
    )
    agent.monitor_profile = (
        monitor_profile if isinstance(monitor_profile, str) else None
    )
    agent.monitor_policy_digest = (
        monitor_policy_digest if isinstance(monitor_policy_digest, str) else None
    )
    if isinstance(monitor_timeout_seconds, (int, float)) and not isinstance(
        monitor_timeout_seconds, bool
    ):
        agent.monitor_timeout_seconds = float(monitor_timeout_seconds)
    if isinstance(monitor_idle_timeout_seconds, (int, float)) and not isinstance(
        monitor_idle_timeout_seconds, bool
    ):
        agent.monitor_idle_timeout_seconds = float(monitor_idle_timeout_seconds)
    agent.monitor_output_truncated = bool(monitor_output_truncated)
    agent.monitor_diagnostic_manifest_ref = _string_or_none(
        monitor_diagnostic_manifest_ref
    )
    agent.monitor_retained_log_ref = _string_or_none(monitor_retained_log_ref)
    agent.continuation_monitor_result_id = _string_or_none(
        continuation_monitor_result_id
    )
    agent.continuation_monitor_result_ref = _string_or_none(
        continuation_monitor_result_ref
    )
    agent.continuation_checkpoint_ref = _string_or_none(continuation_checkpoint_ref)
    agent.continuation_node_ref = _string_or_none(continuation_node_ref)
    agent.continuation_manifest_ref = _string_or_none(continuation_manifest_ref)
    agent.monitor_budget_decision_path = _string_or_none(monitor_budget_decision_path)
    agent.monitor_followup_outcome = (
        monitor_followup_outcome if isinstance(monitor_followup_outcome, str) else None
    )
    agent.monitor_followup_error = (
        monitor_followup_error if isinstance(monitor_followup_error, str) else None
    )
    agent.monitor_followup_agent = _string_or_none(monitor_followup_agent)
    agent.monitor_followup_degraded_reason = _string_or_none(
        monitor_followup_degraded_reason
    )
    agent.monitor_followup_prompt_path = _string_or_none(monitor_followup_prompt_path)
    agent.monitor_host_completion_status = _string_or_none(
        monitor_host_completion_status
    )
    agent.monitor_host_completion_message = _string_or_none(
        monitor_host_completion_message
    )
    agent.monitor_host_completion_reason = _string_or_none(
        monitor_host_completion_reason
    )
    if not monitor_member:
        return
    _set_optional_string(agent, "process_identity", monitor_supervisor_identity)
    agent.status_bucket = monitor_state_bucket(state)
    if state == MONITOR_HELD_STATE:
        agent.status = NOT_ADOPTED_STATUS
    elif state == "running" and agent.status != "STARTING":
        agent.status = clamp_monitor_status_or_default(
            monitor_start_status if isinstance(monitor_start_status, str) else None,
            default=DEFAULT_MONITOR_START_STATUS,
        )


def apply_monitor_done(
    agent: Agent,
    *,
    monitor_state: object,
    monitor_exit_code: object,
    status_label: object,
    monitor_followup_outcome: object = None,
    monitor_followup_error: object = None,
    monitor_followup_agent: object = None,
    monitor_followup_degraded_reason: object = None,
    monitor_followup_prompt_path: object = None,
    monitor_host_completion_status: object = None,
    monitor_host_completion_message: object = None,
    monitor_host_completion_reason: object = None,
    monitor_diagnostic_manifest_ref: object = None,
    monitor_retained_log_ref: object = None,
    continuation_monitor_result_id: object = None,
    continuation_monitor_result_ref: object = None,
    continuation_checkpoint_ref: object = None,
    continuation_node_ref: object = None,
    continuation_manifest_ref: object = None,
    monitor_budget_decision_path: object = None,
    monitor_stage_held: object = False,
) -> None:
    """Apply terminal monitor fields from ``done.json`` to one row."""
    raw_state = monitor_state if isinstance(monitor_state, str) else agent.monitor_state
    state = _projected_monitor_state(raw_state, monitor_stage_held)
    if state is None and isinstance(raw_state, str) and raw_state:
        state = raw_state
    if isinstance(state, str) and state:
        agent.monitor_state = state
        agent.status_bucket = monitor_state_bucket(state)
        if state == MONITOR_HELD_STATE:
            agent.status = NOT_ADOPTED_STATUS
    if type(monitor_exit_code) is int:
        agent.monitor_exit_code = monitor_exit_code
    if isinstance(status_label, str) and status_label and state != MONITOR_HELD_STATE:
        agent.status = status_label
        agent.monitor_stop_status = (
            clamp_monitor_status_or_default(status_label, default="") or None
        )
    if isinstance(monitor_followup_outcome, str) and monitor_followup_outcome:
        agent.monitor_followup_outcome = monitor_followup_outcome
    if isinstance(monitor_followup_error, str) and monitor_followup_error:
        agent.monitor_followup_error = monitor_followup_error
    if isinstance(monitor_followup_agent, str) and monitor_followup_agent:
        agent.monitor_followup_agent = monitor_followup_agent
    if (
        isinstance(monitor_followup_degraded_reason, str)
        and monitor_followup_degraded_reason
    ):
        agent.monitor_followup_degraded_reason = monitor_followup_degraded_reason
    if isinstance(monitor_followup_prompt_path, str) and monitor_followup_prompt_path:
        agent.monitor_followup_prompt_path = monitor_followup_prompt_path
    if (
        isinstance(monitor_host_completion_status, str)
        and monitor_host_completion_status
    ):
        agent.monitor_host_completion_status = monitor_host_completion_status
    if (
        isinstance(monitor_host_completion_message, str)
        and monitor_host_completion_message
    ):
        agent.monitor_host_completion_message = monitor_host_completion_message
    if (
        isinstance(monitor_host_completion_reason, str)
        and monitor_host_completion_reason
    ):
        agent.monitor_host_completion_reason = monitor_host_completion_reason
    _set_optional_string(
        agent, "monitor_diagnostic_manifest_ref", monitor_diagnostic_manifest_ref
    )
    _set_optional_string(agent, "monitor_retained_log_ref", monitor_retained_log_ref)
    _set_optional_string(
        agent, "continuation_monitor_result_id", continuation_monitor_result_id
    )
    _set_optional_string(
        agent, "continuation_monitor_result_ref", continuation_monitor_result_ref
    )
    _set_optional_string(
        agent, "continuation_checkpoint_ref", continuation_checkpoint_ref
    )
    _set_optional_string(agent, "continuation_node_ref", continuation_node_ref)
    _set_optional_string(agent, "continuation_manifest_ref", continuation_manifest_ref)
    _set_optional_string(
        agent, "monitor_budget_decision_path", monitor_budget_decision_path
    )


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _set_optional_string(agent: Agent, field_name: str, value: object) -> None:
    if isinstance(value, str) and value:
        setattr(agent, field_name, value)
