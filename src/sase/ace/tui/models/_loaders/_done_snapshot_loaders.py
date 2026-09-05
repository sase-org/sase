"""Snapshot-backed loaders for completed agents."""

from sase.agent.status_buckets import EPIC_APPROVED_STATUS
from sase.core.agent_scan_wire import (
    DONE_WORKFLOW_DIR_NAMES,
    DONE_WORKFLOW_DIR_PREFIXES,
    AgentArtifactRecordWire,
    AgentArtifactScanWire,
)
from sase.gate_shell.status import DEFAULT_GATE_SHELL_SETTLED_STATUS
from sase.monitor_status import (
    DEFAULT_MONITOR_STOP_STATUS,
    clamp_monitor_status_or_default,
)

from ._done_common import (
    completed_import_transaction,
    done_extra_files,
    enrich_agent_revert_state,
    enrich_missing_commit_metadata,
    import_transaction_is_visible,
)
from ._meta_enrichment import (
    enrich_agent_from_meta_wire,
    enrich_agent_from_prompt_markers_wire,
)
from ._meta_enrichment_common import apply_gate_done, apply_monitor_done
from .._timestamps import parse_timestamp_14_digit
from ..agent import Agent, AgentType


def is_done_record(record: AgentArtifactRecordWire) -> bool:
    """Return True iff *record* lives under a workflow dir that holds done agents."""
    name = record.workflow_dir_name
    if name in DONE_WORKFLOW_DIR_NAMES:
        return True
    return any(name.startswith(p) for p in DONE_WORKFLOW_DIR_PREFIXES)


def build_done_agent_from_record(
    record: AgentArtifactRecordWire,
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> Agent | None:
    """Snapshot-aware mirror of :func:`_load_done_agent_for_dir`."""
    if not record.has_done_marker:
        return None
    done = record.done
    if done is None:
        return None
    if not import_transaction_is_visible(
        record.project_name,
        done.imported_transaction_key,
    ):
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
        error_traceback = done.traceback
    elif outcome == "monitored":
        status = clamp_monitor_status_or_default(
            done.status_label, default=DEFAULT_MONITOR_STOP_STATUS
        )
        error_message = done.error
        error_traceback = None
    elif outcome == "gated":
        status = done.status_label or DEFAULT_GATE_SHELL_SETTLED_STATUS
        error_message = done.error
        error_traceback = None
    elif outcome == "stopped" or done.repeat_stopped:
        # Repeat-chain STOP: skipped by a predecessor's STOP output variable.
        # Keeps ``outcome: "completed"`` for %wait cascading but renders as a
        # non-error terminal STOPPED row (checked before generic completed).
        # Queue cancellation uses ``outcome: "stopped"`` for the same display
        # status without the repeat-chain cascade semantics.
        status = "STOPPED"
        error_message = None
        error_traceback = None
    elif outcome == "plan_rejected":
        status = "PLAN REJECTED"
        error_message = None
        error_traceback = None
    elif outcome == "epic_approved":
        status = EPIC_APPROVED_STATUS
        error_message = None
        error_traceback = None
    else:
        status = "DONE"
        error_message = None
        error_traceback = None
    extra_files = done_extra_files(
        done.plan_path,
        done.markdown_pdf_paths,
        done.image_paths,
        done.video_paths,
    )

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=done.project_file or record.project_file,
        status=status,
        start_time=start_time,
        status_bucket=done.status_bucket,
        workflow=record.workflow_dir_name,
        raw_suffix=timestamp_str,
        response_path=done.response_path,
        diff_path=done.diff_path,
        extra_files=extra_files,
        plan_path=done.plan_path,
        archived_plan_path=done.plan_path,
        step_output=done.step_output,
        record_shape=record.record_shape,
        index_record_dir=record.artifact_dir,
        workspace_num=done.workspace_num,
        workspace_dir=done.workspace_dir,
        bug=bug_by_cl_name.get(cl_name),
        cl_num=cl_by_cl_name.get(cl_name),
        error_message=error_message,
        error_traceback=error_traceback,
        output_path=done.output_path,
        model=done.model,
        llm_provider=done.llm_provider,
        vcs_provider=done.vcs_provider,
        agent_name=done.name,
        hidden=bool(done.hidden),
        approve=bool(done.approve),
        monitor_stop_status=status if outcome == "monitored" else None,
        gate_stop_status=status if outcome == "gated" else None,
    )

    if done.retried_as_timestamp:
        agent.retried_as_timestamp = done.retried_as_timestamp
    if done.retry_chain_root_timestamp:
        agent.retry_chain_root_timestamp = done.retry_chain_root_timestamp
    if done.retry_error_category:
        agent.retry_error_category = done.retry_error_category

    enrich_agent_from_meta_wire(
        agent,
        record.agent_meta,
        record.waiting,
        record.pending_question,
        plan_path_marker=(
            record.plan_path.plan_path if record.plan_path is not None else None
        ),
        has_done_marker=record.has_done_marker,
    )
    done_shell = done.family_shell
    done_monitor_shell = (
        done_shell if done_shell is not None and done_shell.kind == "monitor" else None
    )
    done_monitor = (
        done_monitor_shell.monitor if done_monitor_shell is not None else None
    )
    done_gate_shell = (
        done_shell if done_shell is not None and done_shell.kind == "gate" else None
    )
    done_gate = done_gate_shell.gate if done_gate_shell is not None else None
    if outcome == "monitored":
        apply_monitor_done(
            agent,
            monitor_state=(
                done_monitor_shell.state if done_monitor_shell is not None else None
            ),
            monitor_exit_code=(
                done_monitor.exit_code if done_monitor is not None else None
            ),
            status_label=done.status_label,
            monitor_followup_outcome=(
                done_monitor_shell.followup_outcome
                if done_monitor_shell is not None
                else None
            ),
            monitor_followup_error=(
                done_monitor_shell.followup_error
                if done_monitor_shell is not None
                else None
            ),
        )
    elif outcome == "gated":
        apply_gate_done(
            agent,
            gate_id=done_gate_shell.id if done_gate_shell is not None else None,
            gate_kind=done_gate.kind if done_gate is not None else None,
            gate_state=done_gate_shell.state if done_gate_shell is not None else None,
            gate_elapsed_seconds=(
                done_gate_shell.elapsed_seconds if done_gate_shell is not None else None
            ),
            gate_output_path=(
                done_gate_shell.output_path if done_gate_shell is not None else None
            ),
            gate_output_truncated=(
                done_gate_shell.output_truncated
                if done_gate_shell is not None
                else None
            ),
            gate_bundle_path=done_gate.bundle_path if done_gate is not None else None,
            gate_notification_id=(
                done_gate.notification_id if done_gate is not None else None
            ),
            status_label=done.status_label,
            gate_followup_outcome=(
                done_gate_shell.followup_outcome
                if done_gate_shell is not None
                else None
            ),
            gate_followup_error=(
                done_gate_shell.followup_error if done_gate_shell is not None else None
            ),
            gate_followup_degraded_reason=(
                done_gate_shell.followup_degraded_reason
                if done_gate_shell is not None
                else None
            ),
            gate_followup_prompt_path=(
                done_gate_shell.followup_prompt_path
                if done_gate_shell is not None
                else None
            ),
        )
    enrich_agent_from_prompt_markers_wire(agent, record.prompt_steps)
    enrich_missing_commit_metadata(agent, record.artifact_dir)
    enrich_agent_revert_state(agent, record.artifact_dir)
    return agent


def load_done_agents_from_snapshot(
    snapshot: AgentArtifactScanWire,
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> list[Agent]:
    """Snapshot-aware mirror of :func:`load_done_agents`.

    Iterates pre-walked artifact records from a single
    :class:`AgentArtifactScanWire` instead of re-walking the filesystem.
    """
    completed_import_transaction.cache_clear()
    agents: list[Agent] = []
    for record in snapshot.records:
        if not is_done_record(record):
            continue
        agent = build_done_agent_from_record(record, bug_by_cl_name, cl_by_cl_name)
        if agent is not None:
            agents.append(agent)
    return agents
