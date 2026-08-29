"""Snapshot-aware mirrors of the workflow filesystem loaders.

These functions consume a pre-walked :class:`AgentArtifactScanWire` snapshot
instead of re-reading every marker file from disk.  They produce the same
``WorkflowEntry`` / ``Agent`` shapes as the helpers in
``_workflow_loaders`` and ``_workflow_step_loaders``.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import (
    WORKFLOW_STATE_DIR_NAMES,
    WORKFLOW_STATE_DIR_PREFIXES,
    AgentArtifactRecordWire,
    AgentArtifactScanWire,
)

from ....hooks.processes import is_process_running
from .._timestamps import parse_timestamp_14_digit
from ..agent import Agent, AgentType
from ..workflow import WorkflowEntry
from ._diff_path import diff_path_from_step_output
from ._meta_enrichment import enrich_agent_from_meta, enrich_agent_from_meta_wire
from ._workflow_loaders import (
    ACTIVE_STATUSES,
    SETTLED_FAMILY_SHELL_DONE_OUTCOMES,
    family_shell_member_from_meta,
)
from ._workflow_failure_fallback import (
    build_workflow_failure_fallback,
    preferred_workflow_output_path,
)
from ._workflow_step_loaders import (
    FAMILY_PROGRESSED_PLAN_ACTIONS,
    NON_TERMINAL_STEP_DISPLAY_STATUSES,
    is_plan_step,
)


def _is_workflow_state_record(record: AgentArtifactRecordWire) -> bool:
    """Return True iff *record* lives under a workflow_state-bearing folder."""
    name = record.workflow_dir_name
    if name in WORKFLOW_STATE_DIR_NAMES:
        return True
    return any(name.startswith(p) for p in WORKFLOW_STATE_DIR_PREFIXES)


def _snapshot_record_is_family_shell_member(record: AgentArtifactRecordWire) -> bool:
    """Return whether *record* is a durable family-shell member."""
    meta = record.agent_meta
    if meta is None:
        return False
    shell = meta.family_shell
    gate_id = shell.id if shell is not None and shell.kind == "gate" else None
    return family_shell_member_from_meta(
        agent_family_role=meta.agent_family_role,
        role_suffix=meta.role_suffix,
        gate_id=gate_id,
    )


def load_workflow_states_from_snapshot(
    snapshot: AgentArtifactScanWire,
) -> list[WorkflowEntry]:
    """Snapshot-aware mirror of :func:`load_workflow_states`.

    Walks pre-parsed ``workflow_state.json`` projections from *snapshot*
    instead of re-reading every file. Status mapping, PID liveness gate,
    diff_path discovery, and error propagation match the filesystem
    helper.
    """
    from sase.xprompt import StepState, StepStatus

    entries: list[WorkflowEntry] = []
    for record in snapshot.records:
        if not _is_workflow_state_record(record):
            continue
        wf_state = record.workflow_state
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
                    output=step.output,
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
            if not has_in_progress and not _snapshot_record_is_family_shell_member(
                record
            ):
                display_status = "FAILED"

        # Match _load_workflow_states diff_path discovery: scan steps in
        # reverse for an explicit "diff_path" output.  Arbitrary "path"-typed
        # outputs (e.g. a #sshot screenshot) are NOT diffs.
        diff_path: str | None = None
        for step in reversed(wf_state.steps):
            diff_path = diff_path_from_step_output(step.output)
            if diff_path:
                break

        error_message = wf_state.error
        error_traceback = wf_state.traceback
        if not error_message and display_status == "FAILED":
            for step in wf_state.steps:
                if step.status == "failed" and step.error:
                    error_message = f"Step '{step.name}' failed: {step.error}"
                    error_traceback = step.traceback
                    break

        output_path: str | None = None
        if display_status == "FAILED":
            recorded_output_path = (
                record.agent_meta.output_path if record.agent_meta is not None else None
            )
            output_path = preferred_workflow_output_path(
                cl_name=wf_state.cl_name or "unknown",
                launch_timestamp=record.timestamp,
                recorded_output_path=recorded_output_path,
            )
            if not error_message and not error_traceback:
                fallback = build_workflow_failure_fallback(
                    cl_name=wf_state.cl_name or "unknown",
                    launch_timestamp=record.timestamp,
                    recorded_output_path=recorded_output_path,
                )
                error_message = fallback.error_message
                output_path = fallback.output_path

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
                output_path=output_path,
                activity=wf_state.activity,
            )
        )

    return entries


def load_workflow_agents_from_snapshot(
    snapshot: AgentArtifactScanWire,
    *,
    step_meta_by_parent: dict[str, dict[str, str]] | None = None,
) -> list[Agent]:
    """Snapshot-aware mirror of :func:`load_workflow_agents`."""
    entries = load_workflow_states_from_snapshot(snapshot)

    # Build a lookup from artifact_dir → record so we can pull
    # plan_path and agent_meta from the same snapshot without
    # re-reading those files.
    record_by_dir: dict[str, AgentArtifactRecordWire] = {
        record.artifact_dir: record
        for record in snapshot.records
        if _is_workflow_state_record(record)
    }

    agents: list[Agent] = []
    for entry in entries:
        raw_suffix = Path(entry.artifacts_dir).name if entry.artifacts_dir else None

        record = record_by_dir.get(entry.artifacts_dir or "")
        if (
            record is not None
            and record.done is not None
            and record.done.outcome in SETTLED_FAMILY_SHELL_DONE_OUTCOMES
        ):
            # A settled family-shell member's workflow_state.json is vestigial
            # launch scaffolding; the done marker owns the terminal row.
            continue

        step_output: dict[str, Any] | None = None
        if entry.steps:
            for step in reversed(entry.steps):
                if step.output and isinstance(step.output, dict):
                    step_output = step.output
                    break

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
            plan_path = record.plan_path.plan_path
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
            output_path=entry.output_path,
            activity=entry.activity,
            step_output=step_output,
            record_shape=record.record_shape if record is not None else "full",
            index_record_dir=record.artifact_dir if record is not None else None,
            workspace_num=workspace_num,
        )
        if record is not None:
            enrich_agent_from_meta_wire(
                agent,
                record.agent_meta,
                record.waiting,
                record.pending_question,
                plan_path_marker=plan_path,
            )
        else:
            enrich_agent_from_meta(agent, entry.artifacts_dir)
        agents.append(agent)

    return agents


def _build_workflow_agent_steps_for_record(
    record: AgentArtifactRecordWire,
) -> tuple[list[Agent], dict[str, str]]:
    """Snapshot-aware mirror of :func:`_load_workflow_agent_steps_for_dir`."""
    dir_agents: list[Agent] = []
    dir_meta: dict[str, str] = {}

    parent_wf_error: str | None = None
    parent_wf_traceback: str | None = None
    parent_wf_failed = False
    parent_wf_completed = False
    parent_appears_as_agent = False
    parent_state = record.workflow_state
    if parent_state is not None:
        parent_appears_as_agent = parent_state.appears_as_agent
        if parent_state.status == "failed":
            parent_wf_failed = True
            parent_wf_error = parent_state.error
            parent_wf_traceback = parent_state.traceback
        elif parent_state.status == "completed":
            parent_wf_completed = True

    family_progressed_past_plan = (
        record.agent_meta is not None
        and record.agent_meta.plan_approved
        and record.agent_meta.plan_action in FAMILY_PROGRESSED_PLAN_ACTIONS
    )

    project_file = record.project_file

    for step in record.prompt_steps:
        try:
            start_time = parse_timestamp_14_digit(record.timestamp)

            status = step.status
            if status == "waiting_hitl":
                display_status = "WAITING INPUT"
            elif status == "completed":
                display_status = "DONE"
            elif status == "in_progress":
                display_status = "RUNNING"
            elif status == "failed":
                display_status = "FAILED"
            else:
                display_status = status.upper()

            workflow_name = step.workflow_name
            step_name = step.step_name
            step_type = step.step_type
            step_source = step.step_source
            step_output = step.output
            step_index = step.step_index
            total_steps = step.total_steps
            parent_step_index = step.parent_step_index
            parent_total_steps = step.parent_total_steps
            is_hidden = step.hidden
            is_pre_prompt_step = step.is_pre_prompt_step
            embedded_workflow_name = step.embedded_workflow_name

            if is_pre_prompt_step:
                is_hidden = True

            artifacts_dir_from_marker = step.artifacts_dir
            diff_path = step.diff_path
            error_message = step.error
            error_traceback = step.traceback
            response_path = step.response_path

            if not diff_path:
                diff_path = diff_path_from_step_output(step_output)

            if isinstance(step_output, dict):
                for k, v in step_output.items():
                    if k.startswith("meta_") and v:
                        dir_meta[k] = str(v)

            agent = Agent(
                agent_type=AgentType.WORKFLOW,
                cl_name=step_name,
                project_file=project_file,
                status=display_status,
                start_time=start_time,
                workflow=workflow_name,
                raw_suffix=record.timestamp,
                parent_workflow=workflow_name,
                parent_timestamp=record.timestamp,
                step_name=step_name,
                step_type=step_type,
                step_source=step_source,
                step_output=step_output,
                record_shape=record.record_shape,
                index_record_dir=record.artifact_dir,
                prompt_step_file_name=step.file_name,
                step_index=step_index,
                total_steps=total_steps,
                parent_step_index=parent_step_index,
                parent_total_steps=parent_total_steps,
                is_hidden_step=is_hidden,
                parent_appears_as_agent=parent_appears_as_agent,
                artifacts_dir=artifacts_dir_from_marker,
                diff_path=diff_path,
                error_message=error_message,
                error_traceback=error_traceback,
                response_path=response_path,
                embedded_workflow_name=embedded_workflow_name,
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
                agent.error_traceback = parent_wf_traceback

            if parent_wf_completed and agent.status == "RUNNING":
                agent.status = "DONE"

            # A step's ``artifacts_dir`` marker field is, in every observed
            # writer and production sample, the same directory the parent
            # record's own artifact_dir names -- the snapshot has therefore
            # already parsed the exact agent_meta.json/waiting.json/
            # pending_question.json/plan_path.json this step would otherwise
            # re-read from disk. Reuse those parsed markers when the dirs
            # match, and fall back to the filesystem helper for the rare
            # case where a step's artifacts_dir genuinely diverges.
            if artifacts_dir_from_marker == record.artifact_dir:
                enrich_agent_from_meta_wire(
                    agent,
                    record.agent_meta,
                    record.waiting,
                    record.pending_question,
                    plan_path_marker=(
                        record.plan_path.plan_path
                        if record.plan_path is not None
                        else None
                    ),
                    workflow_child=True,
                )
            else:
                enrich_agent_from_meta(
                    agent, artifacts_dir_from_marker, workflow_child=True
                )

            if (
                family_progressed_past_plan
                and agent.status in NON_TERMINAL_STEP_DISPLAY_STATUSES
                and is_plan_step(step_name, agent.role_suffix)
            ):
                agent.status = "DONE"

            dir_agents.append(agent)
        except Exception:
            continue

    return dir_agents, dir_meta


def load_workflow_agent_steps_from_snapshot(
    snapshot: AgentArtifactScanWire,
) -> tuple[list[Agent], dict[str, dict[str, str]]]:
    """Snapshot-aware mirror of :func:`load_workflow_agent_steps`.

    Returns the same ``(agents, meta_by_parent)`` shape as the filesystem
    helper, sourcing every prompt-step marker from the pre-walked snapshot
    so the heavy ``glob`` + parallel JSON parsing happens once per refresh.
    """
    agents: list[Agent] = []
    meta_by_parent: dict[str, dict[str, str]] = {}
    for record in snapshot.records:
        if not _is_workflow_state_record(record):
            continue
        if not record.prompt_steps:
            continue
        dir_agents, dir_meta = _build_workflow_agent_steps_for_record(record)
        agents.extend(dir_agents)
        if dir_meta:
            meta_by_parent[record.timestamp] = dir_meta
    return agents, meta_by_parent
