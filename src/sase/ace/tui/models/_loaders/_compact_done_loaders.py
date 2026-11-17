"""Compact-wire loaders for completed agents.

Compact twin of :mod:`sase.ace.tui.models._loaders._done_snapshot_loaders`:
it constructs ordinary done ``Agent`` rows directly from compact list
facts with the same status mapping, metadata enrichment, and action
facts. Deferred detail fields (tracebacks, response/output paths, media
file lists, status-bucket override, monitor/gate diagnostic refs) keep
their ``Agent`` defaults so selected-record hydration (the
workflow-cutover phase) can restore them later.

The constructors read only compact wire dataclasses
(:mod:`sase.core.agent_scan_list_wire`). They never call the full-record
Python decoder and never build full marker dataclasses.
"""

from sase.agent.status_buckets import EPIC_APPROVED_STATUS
from sase.core.agent_scan_wire import (
    DONE_WORKFLOW_DIR_NAMES,
    DONE_WORKFLOW_DIR_PREFIXES,
)
from sase.core.agent_scan_list_wire import (
    AgentArtifactListRecordWire,
    AgentArtifactListSnapshotWire,
)
from sase.gate_turn.status import DEFAULT_GATE_TURN_SETTLED_STATUS
from sase.monitor_status import (
    DEFAULT_MONITOR_STOP_STATUS,
    clamp_monitor_status_or_default,
)

from ._compact_meta_enrichment import enrich_agent_from_compact_meta
from ._compact_prompt_markers import enrich_agent_from_compact_prompt_steps
from ._done_common import (
    done_extra_files,
    lazy_done_instruction_bundle_files,
    enrich_agent_revert_state,
    enrich_missing_commit_metadata,
)
from ._meta_enrichment_common import (
    apply_archive_source_machine,
    apply_imported_source_owner,
)
from ._meta_enrichment_gate import apply_gate_done
from ._meta_enrichment_monitor import apply_monitor_done
from ._meta_enrichment_status import (
    hijack_recovery_is_expired,
    hijack_status_from_done_marker,
)
from .._timestamps import parse_timestamp_14_digit
from ..agent import Agent, AgentType


def is_compact_done_record(record: AgentArtifactListRecordWire) -> bool:
    """Return True iff *record* lives under a workflow dir holding done agents."""
    name = record.workflow_dir_name
    if name in DONE_WORKFLOW_DIR_NAMES:
        return True
    return any(name.startswith(p) for p in DONE_WORKFLOW_DIR_PREFIXES)


def _compact_step_output(record: AgentArtifactListRecordWire) -> dict | None:
    """Reconstruct list-visible step output from compact output facts.

    The projection keeps every ``meta_*`` key plus a string ``diff_path``;
    both are list-consumed (workspace-number fallback, commit backfill,
    header metadata). Other raw output keys are deferred detail and stay
    absent until selected-record hydration.
    """
    done = record.done
    output = done.step_output if done is not None else None
    if output is None:
        return None
    step_output = dict(output.meta)
    if output.diff_path is not None:
        step_output.setdefault("diff_path", output.diff_path)
    return step_output


def _apply_compact_auto_restart(agent: Agent, done: object) -> None:
    """Project the compact done-wire recovery object onto a snapshot agent.

    Compact-local mirror of the full-snapshot helper: an in-flight
    recovery promotes the row from ``FAILED`` to ``RESTARTING``; declined
    and stale-pending rows keep ``FAILED``. Reads only compact recovery
    facts through ``getattr`` so no full-record types are involved.
    """
    recovery = getattr(done, "recovery", None)
    if recovery is None:
        return
    from sase.agent.auto_restart.ux import RESTARTING_STATUS, apply_recovery_to_agent

    restarted = apply_recovery_to_agent(
        agent,
        state=getattr(recovery, "state", None),
        reason=getattr(recovery, "reason", None),
        reason_text=getattr(recovery, "reason_text", None),
        requested_at=getattr(recovery, "requested_at", None),
        updated_at=getattr(recovery, "updated_at", None),
        episode_id=getattr(recovery, "episode_id", None),
    )
    if restarted == RESTARTING_STATUS and agent.status == "FAILED":
        agent.status = RESTARTING_STATUS


def build_done_agent_from_compact_record(
    record: AgentArtifactListRecordWire,
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> Agent | None:
    """Build one done ``Agent`` row directly from compact list facts."""
    if not record.has_done_marker:
        return None
    done = record.done
    if done is None:
        return None
    timestamp_str = record.timestamp
    start_time = parse_timestamp_14_digit(timestamp_str)

    cl_name = done.cl_name or "unknown"
    outcome = done.outcome or "completed"
    if outcome == "noop":
        return None
    if outcome in {"failed", "epic_launch_failed"}:
        if outcome == "failed" and done.retried_as_timestamp:
            status = "FAILED (RETRIED)"
        else:
            status = "FAILED"
        error_message = done.error or (
            "Epic launch failed" if outcome == "epic_launch_failed" else None
        )
    elif outcome == "monitored":
        status = clamp_monitor_status_or_default(
            done.status_label, default=DEFAULT_MONITOR_STOP_STATUS
        )
        error_message = done.error
    elif outcome == "gated":
        status = done.status_label or DEFAULT_GATE_TURN_SETTLED_STATUS
        error_message = done.error
    elif outcome == "stopped" or done.repeat_stopped:
        # Repeat-chain STOP: skipped by a predecessor's STOP output variable.
        # Keeps ``outcome: "completed"`` for %wait cascading but renders as
        # a non-error terminal STOPPED row (checked before generic completed).
        # Queue cancellation uses ``outcome: "stopped"`` for the same display
        # status without the repeat-chain cascade semantics.
        status = "STOPPED"
        error_message = None
    elif outcome == "plan_rejected":
        status = "PLAN REJECTED"
        error_message = None
    elif outcome == "epic_approved":
        status = EPIC_APPROVED_STATUS
        error_message = None
    elif outcome == "hijacked":
        status = hijack_status_from_done_marker(outcome, done.recovery) or "HIJACKED"
        error_message = None
    else:
        status = "DONE"
        error_message = None
    extra_files = done_extra_files(done.plan_path, [], [], [])
    instruction_bundle_files = lazy_done_instruction_bundle_files(record.artifact_dir)

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=done.project_file or record.project_file,
        status=status,
        start_time=start_time,
        workflow=record.workflow_dir_name,
        raw_suffix=timestamp_str,
        diff_path=done.diff_path,
        extra_files=extra_files,
        instruction_bundle_files=instruction_bundle_files,
        plan_path=done.plan_path,
        archived_plan_path=done.plan_path,
        step_output=_compact_step_output(record),
        record_shape="list",
        index_record_dir=record.artifact_dir,
        workspace_num=done.workspace_num,
        workspace_dir=done.workspace_dir,
        bug=bug_by_cl_name.get(cl_name),
        cl_num=cl_by_cl_name.get(cl_name),
        error_message=error_message,
        model=done.model,
        llm_provider=done.llm_provider,
        vcs_provider=done.vcs_provider,
        agent_name=done.name,
        hidden=bool(done.hidden),
        approve=bool(done.approve),
        monitor_stop_status=status if outcome == "monitored" else None,
        gate_stop_status=status if outcome == "gated" else None,
        hijack_expired=hijack_recovery_is_expired(outcome, done.recovery),
        hijack_id=getattr(done.recovery, "hijack_id", None)
        if done.recovery is not None
        else None,
    )

    if done.retried_as_timestamp:
        agent.retried_as_timestamp = done.retried_as_timestamp
    if done.retry_chain_root_timestamp:
        agent.retry_chain_root_timestamp = done.retry_chain_root_timestamp
    if done.retry_error_category:
        agent.retry_error_category = done.retry_error_category

    enrich_agent_from_compact_meta(
        agent,
        record.meta,
        record.waiting,
        record.pending_question,
        plan_path_marker=record.plan_path,
        has_done_marker=record.has_done_marker,
    )
    apply_imported_source_owner(agent, done.imported_source_owner)
    apply_archive_source_machine(agent, done.source_machine)
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
            monitor_host_completion_status=(
                done_monitor_turn.host_completion_status
                if done_monitor_turn is not None
                else None
            ),
        )
    elif outcome == "gated":
        apply_gate_done(
            agent,
            gate_id=done_gate_turn.id if done_gate_turn is not None else None,
            gate_kind=done_gate.kind if done_gate is not None else None,
            gate_state=done_gate_turn.state if done_gate_turn is not None else None,
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
        )
    _apply_compact_auto_restart(agent, done)
    enrich_agent_from_compact_prompt_steps(agent, record.prompt_steps)
    enrich_missing_commit_metadata(agent, record.artifact_dir)
    enrich_agent_revert_state(agent, record.artifact_dir)
    return agent


def load_done_agents_from_compact_snapshot(
    snapshot: AgentArtifactListSnapshotWire,
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> list[Agent]:
    """Build done ``Agent`` rows from one compact list snapshot.

    Compact twin of :func:`load_done_agents_from_snapshot`: iterates
    pre-walked compact records instead of full-shaped snapshot records.
    """
    agents: list[Agent] = []
    for record in snapshot.records:
        if not is_compact_done_record(record):
            continue
        agent = build_done_agent_from_compact_record(
            record, bug_by_cl_name, cl_by_cl_name
        )
        if agent is not None:
            agents.append(agent)
    return agents
