"""Compact-wire loaders for workflow parents and prompt-step children.

Compact twin of :mod:`sase.ace.tui.models._loaders._workflow_snapshot_loaders`:
it constructs ordinary workflow parent and prompt-step child ``Agent`` rows
directly from compact list facts with the same status mapping, PID liveness
gate, diff_path discovery, error propagation, and metadata enrichment.
Detail-only payloads (tracebacks, response paths, full step outputs, media
file lists, instruction manifests, status-bucket override, monitor/gate
command and output payloads) keep their ``Agent`` defaults so
selected-record hydration (``_projected_record``) can restore them later.

The constructors read only compact wire dataclasses
(:mod:`sase.core.agent_scan_list_wire`). They never call the full-record
Python decoder and never build full marker dataclasses.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.agent_scan_list_wire import (
    AgentArtifactListOutputFactsWire,
    AgentArtifactListRecordWire,
    AgentArtifactListSnapshotWire,
)

from .._timestamps import parse_timestamp_14_digit
from ..agent import Agent, AgentType
from ..workflow import WorkflowEntry
from ....hooks.processes import is_process_running
from ._compact_meta_enrichment import enrich_agent_from_compact_meta
from ._compact_prompt_markers import enrich_agent_from_compact_prompt_steps
from ._diff_path import diff_path_from_step_output
from ._meta_enrichment import enrich_agent_from_meta
from ._workflow_failure_fallback import (
    build_workflow_failure_fallback,
    preferred_workflow_output_path,
)
from ._workflow_loaders import (
    ACTIVE_STATUSES,
    SETTLED_AGENT_SESSION_TURN_DONE_OUTCOMES,
    agent_session_turn_member_from_meta,
)
from ._workflow_step_loaders import (
    AGENT_SESSION_PROGRESSED_PLAN_ACTIONS,
    NON_TERMINAL_STEP_DISPLAY_STATUSES,
    is_plan_step,
)


def is_compact_workflow_state_record(record: AgentArtifactListRecordWire) -> bool:
    """Return True iff *record* lives under a workflow_state-bearing folder."""
    from sase.core.agent_scan_wire import (
        WORKFLOW_STATE_DIR_NAMES,
        WORKFLOW_STATE_DIR_PREFIXES,
    )

    name = record.workflow_dir_name
    if name in WORKFLOW_STATE_DIR_NAMES:
        return True
    return any(name.startswith(p) for p in WORKFLOW_STATE_DIR_PREFIXES)


def _snapshot_record_is_agent_session_turn_member(
    record: AgentArtifactListRecordWire,
) -> bool:
    """Return whether *record* is a durable agent-session-turn member."""
    meta = record.meta
    if meta is None:
        return False
    turn = meta.agent_session_turn
    gate_id = turn.id if turn is not None and turn.kind == "gate" else None
    return agent_session_turn_member_from_meta(
        agent_session_role=meta.agent_session_role,
        role_suffix=meta.role_suffix,
        gate_id=gate_id,
    )


def _compact_step_output_dict(
    output: AgentArtifactListOutputFactsWire | None,
) -> dict[str, Any] | None:
    """Reconstruct list-visible step output from compact output facts.

    The projection keeps every ``meta_*`` key plus a string ``diff_path``;
    other raw output keys are deferred detail and stay absent until
    selected-record hydration.
    """
    if output is None:
        return None
    step_output = dict(output.meta)
    if output.diff_path is not None:
        step_output.setdefault("diff_path", output.diff_path)
    return step_output


def _compact_workflow_step_output(
    record: AgentArtifactListRecordWire,
) -> dict[str, Any] | None:
    """Return the last list-visible workflow step output for a parent row."""
    workflow = record.workflow
    if workflow is None:
        return None
    for step in reversed(workflow.steps):
        output = _compact_step_output_dict(step.output)
        if output:
            return output
    return None


def load_compact_workflow_states_from_snapshot(
    snapshot: AgentArtifactListSnapshotWire,
) -> list[WorkflowEntry]:
    """Compact twin of :func:`load_workflow_states_from_snapshot`.

    Walks compact workflow projections instead of full-shaped snapshot
    records. Status mapping, PID liveness gate, diff_path discovery, and
    error propagation match the full helper.
    """
    from sase.macro import StepState, StepStatus

    entries: list[WorkflowEntry] = []
    for record in snapshot.records:
        if not is_compact_workflow_state_record(record):
            continue
        wf_state = record.workflow
        if wf_state is None:
            continue

        start_time = parse_timestamp_14_digit(record.timestamp)
        if start_time is None and wf_state.start_time:
            try:
                start_time = datetime.fromisoformat(wf_state.start_time)
            except ValueError:
                pass

        status = wf_state.status
        if status == "waiting_hitl":
            display_status = "WAITING INPUT"
        elif status == "completed":
            display_status = "DONE"
        elif status == "failed":
            display_status = "FAILED"
        else:
            display_status = "RUNNING"

        steps: list[StepState] = []
        for step in wf_state.steps:
            try:
                step_status = StepStatus(step.status)
            except ValueError:
                step_status = StepStatus("pending")
            steps.append(
                StepState(
                    name=step.name,
                    status=step_status,
                    output=_compact_step_output_dict(step.output),
                    error=step.error,
                )
            )

        pid = wf_state.pid
        if (
            display_status in ACTIVE_STATUSES
            and pid is not None
            and not is_process_running(pid)
        ):
            has_in_progress = any(s.status == StepStatus.IN_PROGRESS for s in steps)
            if (
                not has_in_progress
                and not _snapshot_record_is_agent_session_turn_member(record)
            ):
                display_status = "FAILED"

        # Match the full loader's diff_path discovery: scan steps in
        # reverse for an explicit "diff_path" output. Arbitrary "path"-typed
        # outputs (e.g. a #sshot screenshot) are NOT diffs.
        diff_path: str | None = None
        for step in reversed(wf_state.steps):
            diff_path = diff_path_from_step_output(
                _compact_step_output_dict(step.output)
            )
            if diff_path:
                break

        error_message = wf_state.error
        error_traceback = None
        if not error_message and display_status == "FAILED":
            for step in wf_state.steps:
                if step.status == "failed" and step.error:
                    error_message = f"Step '{step.name}' failed: {step.error}"
                    break

        output_path: str | None = None
        error_is_synthetic = False
        if display_status == "FAILED":
            recorded_output_path = (
                record.meta.output_path if record.meta is not None else None
            )
            output_path = preferred_workflow_output_path(
                cl_name=wf_state.cl_name or "unknown",
                launch_timestamp=record.timestamp,
                recorded_output_path=recorded_output_path,
            )
            if not error_message:
                fallback = build_workflow_failure_fallback(
                    cl_name=wf_state.cl_name or "unknown",
                    launch_timestamp=record.timestamp,
                    recorded_output_path=recorded_output_path,
                )
                error_message = fallback.error_message
                output_path = fallback.output_path
                error_is_synthetic = True

        entries.append(
            WorkflowEntry(
                workflow_name=wf_state.workflow_name,
                cl_name=wf_state.cl_name or "unknown",
                project_file=record.project_file,
                status=display_status,
                current_step=wf_state.current_step_index,
                total_steps=len(steps),
                steps=steps,
                start_time=start_time,
                artifacts_dir=record.artifact_dir,
                pid=pid,
                appears_as_agent=wf_state.appears_as_agent,
                is_anonymous=wf_state.is_anonymous,
                hidden=wf_state.hidden,
                diff_path=diff_path,
                error_message=error_message,
                error_traceback=error_traceback,
                error_is_synthetic=error_is_synthetic,
                output_path=output_path,
                activity=wf_state.activity,
            )
        )

    return entries


def load_compact_workflow_agents_from_snapshot(
    snapshot: AgentArtifactListSnapshotWire,
    *,
    step_meta_by_parent: dict[str, dict[str, str]] | None = None,
) -> list[Agent]:
    """Compact twin of :func:`load_workflow_agents_from_snapshot`."""
    entries = load_compact_workflow_states_from_snapshot(snapshot)

    record_by_dir: dict[str, AgentArtifactListRecordWire] = {
        record.artifact_dir: record
        for record in snapshot.records
        if is_compact_workflow_state_record(record)
    }

    agents: list[Agent] = []
    for entry in entries:
        raw_suffix = Path(entry.artifacts_dir).name if entry.artifacts_dir else None

        record = record_by_dir.get(entry.artifacts_dir or "")
        if (
            record is not None
            and record.done is not None
            and record.done.outcome in SETTLED_AGENT_SESSION_TURN_DONE_OUTCOMES
        ):
            # A settled session-turn member's workflow_state.json is vestigial
            # launch scaffolding; the done marker owns the terminal row.
            continue

        step_output = (
            _compact_workflow_step_output(record) if record is not None else None
        )

        if step_meta_by_parent is not None and raw_suffix:
            meta = step_meta_by_parent.get(raw_suffix)
            if meta:
                if step_output is None:
                    step_output = {}
                else:
                    step_output = dict(step_output)
                step_output.update(meta)

        workspace_num = None
        if step_output and step_output.get("meta_workspace"):
            try:
                workspace_num = int(step_output["meta_workspace"])
            except (ValueError, TypeError):
                pass

        extra_files: list[str] = []
        plan_path: str | None = None
        if record is not None and record.plan_path is not None:
            plan_path = record.plan_path
            if plan_path:
                extra_files = [plan_path]

        agent = Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name=entry.cl_name,
            project_file=entry.project_file,
            status=entry.status,
            start_time=entry.start_time,
            workflow=entry.workflow_name,
            raw_suffix=raw_suffix,
            pid=entry.pid,
            appears_as_agent=entry.appears_as_agent,
            is_anonymous=entry.is_anonymous,
            hidden=entry.hidden,
            artifacts_dir=entry.artifacts_dir,
            diff_path=entry.diff_path,
            extra_files=extra_files,
            plan_path=plan_path,
            archived_plan_path=plan_path,
            error_message=entry.error_message,
            error_traceback=entry.error_traceback,
            error_is_synthetic=entry.error_is_synthetic,
            output_path=entry.output_path,
            activity=entry.activity,
            step_output=step_output,
            record_shape="list",
            index_record_dir=record.artifact_dir if record is not None else None,
            workspace_num=workspace_num,
        )
        if record is not None:
            enrich_agent_from_compact_meta(
                agent,
                record.meta,
                record.waiting,
                record.pending_question,
                plan_path_marker=plan_path,
                has_done_marker=record.has_done_marker,
            )
            if agent.is_monitor and agent.pid is None:
                # Monitor workflow scaffolding has no PID; the supervisor
                # stamps metadata (or the running marker). Probes own liveness.
                agent.pid = record.meta.pid if record.meta else None
                if record.running is not None:
                    if agent.pid is None:
                        agent.pid = record.running.pid
                    if agent.process_identity is None:
                        agent.process_identity = record.running.process_identity
                if agent.pid is not None:
                    agent.pid_liveness_unverified = True
        else:
            enrich_agent_from_meta(agent, entry.artifacts_dir)
        agents.append(agent)

    return agents


def _compact_step_display_status(status: str) -> str:
    """Map a compact prompt-step status to its display string."""
    if status == "waiting_hitl":
        return "WAITING INPUT"
    if status == "completed":
        return "DONE"
    if status == "in_progress":
        return "RUNNING"
    if status == "failed":
        return "FAILED"
    return status.upper()


def _build_compact_workflow_agent_steps_for_record(
    record: AgentArtifactListRecordWire,
) -> tuple[list[Agent], dict[str, str]]:
    """Compact twin of :func:`_build_workflow_agent_steps_for_record`."""
    dir_agents: list[Agent] = []
    dir_meta: dict[str, str] = {}

    parent_wf_error: str | None = None
    parent_wf_failed = False
    parent_wf_completed = False
    parent_appears_as_agent = False
    parent_state = record.workflow
    if parent_state is not None:
        parent_appears_as_agent = parent_state.appears_as_agent
        if parent_state.status == "failed":
            parent_wf_failed = True
            parent_wf_error = parent_state.error
        elif parent_state.status == "completed":
            parent_wf_completed = True

    agent_session_progressed_past_plan = (
        record.meta is not None
        and record.meta.plan_approved
        and record.meta.plan_action in AGENT_SESSION_PROGRESSED_PLAN_ACTIONS
    )

    project_file = record.project_file

    for step in record.prompt_steps:
        try:
            start_time = parse_timestamp_14_digit(record.timestamp)

            display_status = _compact_step_display_status(step.status)

            step_output = _compact_step_output_dict(step.output)
            is_hidden = step.hidden
            is_pre_prompt_step = step.is_pre_prompt_step

            if is_pre_prompt_step:
                is_hidden = True

            artifacts_dir_from_marker = step.artifacts_dir
            diff_path = step.diff_path
            error_message = step.error

            if not diff_path:
                diff_path = diff_path_from_step_output(step_output)

            if isinstance(step_output, dict):
                for k, v in step_output.items():
                    if k.startswith("meta_") and v:
                        dir_meta[k] = str(v)

            agent = Agent(
                agent_type=AgentType.WORKFLOW,
                cl_name=step.step_name,
                project_file=project_file,
                status=display_status,
                start_time=start_time,
                workflow=step.workflow_name,
                raw_suffix=record.timestamp,
                parent_workflow=step.workflow_name,
                parent_timestamp=record.timestamp,
                step_name=step.step_name,
                step_type=step.step_type,
                step_source=step.step_source,
                step_output=step_output,
                record_shape="list",
                index_record_dir=record.artifact_dir,
                prompt_step_file_name=step.file_name,
                step_index=step.step_index,
                total_steps=step.total_steps,
                parent_step_index=step.parent_step_index,
                parent_total_steps=step.parent_total_steps,
                is_hidden_step=is_hidden,
                parent_appears_as_agent=parent_appears_as_agent,
                artifacts_dir=artifacts_dir_from_marker,
                diff_path=diff_path,
                error_message=error_message,
                error_traceback=None,
                response_path=None,
                embedded_workflow_name=step.embedded_workflow_name,
                is_pre_prompt_step=is_pre_prompt_step,
                model=step.model,
                llm_provider=step.llm_provider,
                reasoning_effort=step.reasoning_effort,
                model_alias=step.model_alias,
            )

            if (
                parent_wf_failed
                and agent.status == "RUNNING"
                and not agent.error_message
            ):
                agent.status = "FAILED"
                agent.error_message = parent_wf_error

            if parent_wf_completed and agent.status == "RUNNING":
                agent.status = "DONE"

            # A step's ``artifacts_dir`` marker field is, in every observed
            # writer and production sample, the same directory the parent
            # record's own artifact_dir names -- the compact projection has
            # therefore already narrowed the exact agent_meta.json/waiting.json
            # /pending_question.json/plan_path.json this step would otherwise
            # re-read from disk. Reuse those compact facts when the dirs
            # match, and fall back to the filesystem helper for the rare
            # case where a step's artifacts_dir genuinely diverges.
            if artifacts_dir_from_marker == record.artifact_dir:
                enrich_agent_from_compact_meta(
                    agent,
                    record.meta,
                    record.waiting,
                    record.pending_question,
                    plan_path_marker=record.plan_path,
                    workflow_child=True,
                    has_done_marker=record.has_done_marker,
                )
            else:
                enrich_agent_from_meta(
                    agent, artifacts_dir_from_marker, workflow_child=True
                )

            if (
                agent_session_progressed_past_plan
                and agent.status in NON_TERMINAL_STEP_DISPLAY_STATUSES
                and is_plan_step(step.step_name, agent.role_suffix)
            ):
                agent.status = "DONE"

            dir_agents.append(agent)
        except Exception:
            continue

    return dir_agents, dir_meta


def load_compact_workflow_agent_steps_from_snapshot(
    snapshot: AgentArtifactListSnapshotWire,
) -> tuple[list[Agent], dict[str, dict[str, str]]]:
    """Compact twin of :func:`load_workflow_agent_steps_from_snapshot`.

    Returns the same ``(agents, meta_by_parent)`` shape as the full
    helper, sourcing every prompt-step marker from the compact projection
    so no per-step JSON parsing happens per refresh.
    """
    agents: list[Agent] = []
    meta_by_parent: dict[str, dict[str, str]] = {}
    for record in snapshot.records:
        if not is_compact_workflow_state_record(record):
            continue
        if not record.prompt_steps:
            continue
        dir_agents, dir_meta = _build_compact_workflow_agent_steps_for_record(record)
        agents.extend(dir_agents)
        if dir_meta:
            meta_by_parent[record.timestamp] = dir_meta
    return agents, meta_by_parent


__all__ = [
    "is_compact_workflow_state_record",
    "load_compact_workflow_agent_steps_from_snapshot",
    "load_compact_workflow_agents_from_snapshot",
    "load_compact_workflow_states_from_snapshot",
]
