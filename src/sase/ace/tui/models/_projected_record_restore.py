"""Apply detached full records and restore deferred detail."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.core.agent_scan_wire import AgentArtifactRecordWire, PromptStepMarkerWire

from .agent_types import AgentType
from ._loaders._meta_enrichment_identity import parse_linked_repos
from ._projected_record_detail import (
    mark_projected_agent_hydration_attempted,
    note_projected_detail_retained,
    stash_applied_detail,
)

if TYPE_CHECKING:
    from .agent import Agent


def apply_projected_agent_record(
    agent: Agent,
    record: AgentArtifactRecordWire,
    *,
    expected_artifact_dir: str,
) -> bool:
    """Apply a detached full-record result to its still-current compact row."""
    if (
        agent.record_shape != "list"
        or agent.index_record_dir != expected_artifact_dir
        or record.artifact_dir != expected_artifact_dir
    ):
        return False

    # The full record stays transient: only its detail values are applied,
    # and the pre-hydration list facts are stashed so the bounded
    # selected-detail owner can release them without re-reading the index.
    # The detached ``record`` drops out of scope here; nothing retains the
    # wire tree.
    pre_hydration = dict(vars(agent))
    _apply_full_record(agent, record)
    agent.record_shape = "full"
    stash_applied_detail(agent, pre_hydration)
    note_projected_detail_retained(agent)
    mark_projected_agent_hydration_attempted(agent)
    return True


def _apply_full_record(agent: Agent, record: AgentArtifactRecordWire) -> bool:
    changed = False
    output = _full_step_output_for_agent(agent, record)
    if output is not None:
        merged = _merge_step_output(agent.step_output, output)
        if merged != agent.step_output:
            agent.step_output = merged
            changed = True

    if record.agent_meta is not None:
        linked_repos = parse_linked_repos(record.agent_meta.linked_repos)
        if linked_repos != agent.linked_repos:
            agent.linked_repos = linked_repos
            changed = True

    if record.artifact_dir and record.artifact_dir != agent.index_record_dir:
        agent.index_record_dir = record.artifact_dir
        changed = True

    if _restore_deferred_meta_detail(agent, record):
        changed = True
    if _restore_deferred_row_detail(agent, record):
        changed = True

    return changed


def _is_list_owned_mirrored_session_root(agent: Agent) -> bool:
    """Whether *agent* is a session container whose list-owned bucket must stick.

    Selected-detail hydration writes ``status_bucket`` from meta/done wires.
    A mirrored session root already carries the list-owned aggregate bucket
    that the Agents tab grouped it under; overwriting it would regroup the
    painted row without a roster rebuild.
    """
    return bool(agent.is_agent_session_container_row)


def _restore_deferred_meta_detail(
    agent: Agent, record: AgentArtifactRecordWire
) -> bool:
    """Restore detail-only meta/waiting/turn facts onto a projected row.

    The compact projection defers linked repositories, output variables,
    the status-bucket override, held-by/hold-expiry facts, and the full
    monitor/gate command and output payloads. The full wire enrichment
    sets identical values for every kept list fact, so re-running it here
    only fills the deferred detail without changing list behavior.
    """
    from ._loaders._meta_enrichment_wire import enrich_agent_from_meta_wire

    if record.agent_meta is None and record.waiting is None:
        return False
    list_status_bucket = agent.status_bucket
    before = (
        agent.linked_repos,
        agent.output_variables,
        agent.status_bucket,
        agent.held_by,
        agent.hold_expires_at,
        agent.response_path,
        agent.output_path,
        agent.error_traceback,
    )
    enrich_agent_from_meta_wire(
        agent,
        record.agent_meta,
        record.waiting,
        record.pending_question,
        plan_path_marker=(
            record.plan_path.plan_path if record.plan_path is not None else None
        ),
        workflow_child=bool(agent.prompt_step_file_name),
        has_done_marker=record.has_done_marker,
    )
    if (
        _is_list_owned_mirrored_session_root(agent)
        and agent.status_bucket != list_status_bucket
    ):
        agent.status_bucket = list_status_bucket
    after = (
        agent.linked_repos,
        agent.output_variables,
        agent.status_bucket,
        agent.held_by,
        agent.hold_expires_at,
        agent.response_path,
        agent.output_path,
        agent.error_traceback,
    )
    return before != after


def _restore_deferred_row_detail(agent: Agent, record: AgentArtifactRecordWire) -> bool:
    """Restore detail-only row facts for the agent's own row kind.

    Done rows regain their status-bucket override, response/output paths,
    failure traceback, media file lists, and full monitor/gate turn facts.
    Workflow parents regain their failure traceback; prompt-step children
    regain their response path and traceback. Fields that already carry
    list-time parity values are left untouched.
    """
    changed = False
    if agent.prompt_step_file_name:
        step = _matching_prompt_step(agent, record)
        if step is not None:
            if step.response_path and agent.response_path != step.response_path:
                agent.response_path = step.response_path
                changed = True
            if step.traceback and agent.error_traceback != step.traceback:
                agent.error_traceback = step.traceback
                changed = True
        return changed

    if agent.agent_type is AgentType.WORKFLOW:
        traceback = _full_workflow_traceback(record)
        if traceback and agent.error_traceback != traceback:
            agent.error_traceback = traceback
            changed = True
        return changed

    done = record.done
    if done is None:
        return changed
    if (
        done.status_bucket
        and agent.status_bucket != done.status_bucket
        and not _is_list_owned_mirrored_session_root(agent)
    ):
        agent.status_bucket = done.status_bucket
        changed = True
    if done.response_path and agent.response_path != done.response_path:
        agent.response_path = done.response_path
        changed = True
    if done.output_path and agent.output_path != done.output_path:
        agent.output_path = done.output_path
        changed = True
    if (done.outcome in {"failed", "epic_launch_failed"}) and done.traceback:
        if agent.error_traceback != done.traceback:
            agent.error_traceback = done.traceback
            changed = True
    from ._loaders._done_common import done_extra_files

    media_files = done_extra_files(
        done.plan_path,
        done.markdown_pdf_paths,
        done.image_paths,
        done.video_paths,
    )
    if media_files != agent.extra_files:
        agent.extra_files = media_files
        changed = True
    if _restore_deferred_done_turn_detail(agent, record):
        changed = True
    return changed


def _restore_deferred_done_turn_detail(
    agent: Agent, record: AgentArtifactRecordWire
) -> bool:
    """Re-apply full monitor/gate turn facts for settled done rows.

    The compact done constructor applies the same helpers with the shared
    turn wire, but the done-marker diagnostic refs and turn follow-up
    payload paths are deferred. Re-running with full values only fills
    those detail fields; the settled display status is unchanged.
    """
    from sase.gate_turn.status import DEFAULT_GATE_TURN_SETTLED_STATUS
    from sase.monitor_status import (
        DEFAULT_MONITOR_STOP_STATUS,
        clamp_monitor_status_or_default,
    )

    from ._loaders._meta_enrichment_gate import apply_gate_done
    from ._loaders._meta_enrichment_monitor import apply_monitor_done

    done = record.done
    if done is None:
        return False
    outcome = done.outcome or "completed"
    before = (
        agent.monitor_stop_status,
        agent.gate_stop_status,
        agent.monitor_followup_prompt_path
        if hasattr(agent, "monitor_followup_prompt_path")
        else None,
    )
    done_turn = done.agent_session_turn
    done_monitor_turn = (
        done_turn if done_turn is not None and done_turn.kind == "monitor" else None
    )
    done_monitor = done_monitor_turn.monitor if done_monitor_turn is not None else None
    done_gate_turn = (
        done_turn if done_turn is not None and done_turn.kind == "gate" else None
    )
    done_gate = done_gate_turn.gate if done_gate_turn is not None else None
    if outcome == "monitored":
        apply_monitor_done(
            agent,
            monitor_state=(
                done_monitor_turn.state if done_monitor_turn is not None else None
            ),
            monitor_exit_code=(
                done_monitor.exit_code if done_monitor is not None else None
            ),
            status_label=done.status_label,
            monitor_followup_outcome=(
                done_monitor_turn.followup_outcome
                if done_monitor_turn is not None
                else None
            ),
            monitor_followup_error=(
                done_monitor_turn.followup_error
                if done_monitor_turn is not None
                else None
            ),
            monitor_followup_agent=(
                done_monitor_turn.followup_agent
                if done_monitor_turn is not None
                else None
            ),
            monitor_followup_degraded_reason=(
                done_monitor_turn.followup_degraded_reason
                if done_monitor_turn is not None
                else None
            ),
            monitor_followup_prompt_path=(
                done_monitor_turn.followup_prompt_path
                if done_monitor_turn is not None
                else None
            ),
            monitor_host_completion_status=(
                done_monitor_turn.host_completion_status
                if done_monitor_turn is not None
                else None
            ),
            monitor_host_completion_message=(
                done_monitor_turn.host_completion_message
                if done_monitor_turn is not None
                else None
            ),
            monitor_host_completion_reason=(
                done_monitor_turn.host_completion_reason
                if done_monitor_turn is not None
                else None
            ),
            monitor_diagnostic_manifest_ref=done.monitor_diagnostic_manifest_ref,
            monitor_retained_log_ref=done.monitor_retained_log_ref,
            continuation_monitor_result_id=done.continuation_monitor_result_id,
            continuation_monitor_result_ref=done.continuation_monitor_result_ref,
            continuation_checkpoint_ref=done.continuation_checkpoint_ref,
            continuation_node_ref=done.continuation_node_ref,
            continuation_manifest_ref=done.continuation_manifest_ref,
            monitor_budget_decision_path=(
                done.continuation_budget_decision_path
                or done.monitor_followup_budget_decision_path
            ),
        )
    elif outcome == "gated":
        apply_gate_done(
            agent,
            gate_id=done_gate_turn.id if done_gate_turn is not None else None,
            gate_kind=done_gate.kind if done_gate is not None else None,
            gate_state=done_gate_turn.state if done_gate_turn is not None else None,
            gate_elapsed_seconds=(
                done_gate_turn.elapsed_seconds if done_gate_turn is not None else None
            ),
            gate_output_path=(
                done_gate_turn.output_path if done_gate_turn is not None else None
            ),
            gate_output_truncated=(
                done_gate_turn.output_truncated if done_gate_turn is not None else None
            ),
            gate_bundle_path=done_gate.bundle_path if done_gate is not None else None,
            gate_notification_id=(
                done_gate.notification_id if done_gate is not None else None
            ),
            status_label=done.status_label,
            gate_followup_outcome=(
                done_gate_turn.followup_outcome if done_gate_turn is not None else None
            ),
            gate_followup_error=(
                done_gate_turn.followup_error if done_gate_turn is not None else None
            ),
            gate_followup_degraded_reason=(
                done_gate_turn.followup_degraded_reason
                if done_gate_turn is not None
                else None
            ),
            gate_followup_prompt_path=(
                done_gate_turn.followup_prompt_path
                if done_gate_turn is not None
                else None
            ),
        )
    else:
        return False
    # The settled status label is authoritative list state; convergence must
    # never rewrite it from detail values.
    if outcome == "monitored":
        agent.monitor_stop_status = clamp_monitor_status_or_default(
            done.status_label, default=DEFAULT_MONITOR_STOP_STATUS
        )
    elif outcome == "gated":
        agent.gate_stop_status = done.status_label or DEFAULT_GATE_TURN_SETTLED_STATUS
    after = (
        agent.monitor_stop_status,
        agent.gate_stop_status,
        agent.monitor_followup_prompt_path
        if hasattr(agent, "monitor_followup_prompt_path")
        else None,
    )
    return before != after


def _full_workflow_traceback(record: AgentArtifactRecordWire) -> str | None:
    """Return the workflow failure traceback the full loader would set."""
    workflow_state = record.workflow_state
    if workflow_state is None:
        return None
    if workflow_state.traceback:
        return workflow_state.traceback
    for step in workflow_state.steps:
        if step.status == "failed" and step.traceback:
            return step.traceback
    return None


def _full_step_output_for_agent(
    agent: Agent,
    record: AgentArtifactRecordWire,
) -> dict[str, Any] | None:
    if agent.is_workflow_child:
        step = _matching_prompt_step(agent, record)
        return step.output if step is not None else None

    if agent.agent_type is AgentType.WORKFLOW and record.workflow_state is not None:
        for workflow_step in reversed(record.workflow_state.steps):
            if isinstance(workflow_step.output, dict):
                return workflow_step.output
        return None

    if record.done is not None and isinstance(record.done.step_output, dict):
        return record.done.step_output
    return None


def _matching_prompt_step(
    agent: Agent,
    record: AgentArtifactRecordWire,
) -> PromptStepMarkerWire | None:
    if agent.prompt_step_file_name:
        for step in record.prompt_steps:
            if step.file_name == agent.prompt_step_file_name:
                return step

    for step in record.prompt_steps:
        if step.step_index == agent.step_index and step.step_name == agent.step_name:
            return step
    return None


def _merge_step_output(
    existing: dict[str, Any] | None,
    loaded: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(loaded)
    if isinstance(existing, dict):
        for key, value in existing.items():
            merged.setdefault(key, value)
    return merged
