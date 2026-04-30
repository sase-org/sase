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
from ._meta_enrichment import enrich_agent_from_meta, enrich_agent_from_meta_wire
from ._workflow_loaders import ACTIVE_STATUSES


def _is_workflow_state_record(record: AgentArtifactRecordWire) -> bool:
    """Return True iff *record* lives under a workflow_state-bearing folder."""
    name = record.workflow_dir_name
    if name in WORKFLOW_STATE_DIR_NAMES:
        return True
    return any(name.startswith(p) for p in WORKFLOW_STATE_DIR_PREFIXES)


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
            if not has_in_progress:
                display_status = "FAILED"

        # Match _load_workflow_states diff_path discovery: scan steps in
        # reverse for an explicit "diff_path" output, then fall back to
        # the last step's first path-typed output.
        diff_path: str | None = None
        for step in reversed(wf_state.steps):
            if isinstance(step.output, dict) and step.output.get("diff_path"):
                diff_path = str(step.output["diff_path"])
                break
        if not diff_path and wf_state.steps:
            last_step = wf_state.steps[-1]
            output_types = last_step.output_types or {}
            if output_types and isinstance(last_step.output, dict):
                for field_name, field_type in output_types.items():
                    if field_type == "path":
                        path_value = last_step.output.get(field_name)
                        if path_value:
                            diff_path = str(path_value)
                            break

        error_message = wf_state.error
        error_traceback = wf_state.traceback
        if not error_message and display_status == "FAILED":
            for step in wf_state.steps:
                if step.status == "failed" and step.error:
                    error_message = f"Step '{step.name}' failed: {step.error}"
                    error_traceback = step.traceback
                    break

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
                diff_path=diff_path,
                error_message=error_message,
                error_traceback=error_traceback,
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
        record = record_by_dir.get(entry.artifacts_dir or "")
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
            artifacts_dir=entry.artifacts_dir,
            diff_path=entry.diff_path,
            extra_files=extra_files,
            error_message=entry.error_message,
            error_traceback=entry.error_traceback,
            step_output=step_output,
            workspace_num=workspace_num,
        )
        if record is not None:
            enrich_agent_from_meta_wire(agent, record.agent_meta, record.waiting)
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
    parent_state = record.workflow_state
    if parent_state is not None:
        if parent_state.status == "failed":
            parent_wf_failed = True
            parent_wf_error = parent_state.error
            parent_wf_traceback = parent_state.traceback
        elif parent_state.status == "completed":
            parent_wf_completed = True

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
                output_types = step.output_types or {}
                if output_types and isinstance(step_output, dict):
                    for field_name, field_type in output_types.items():
                        if field_type == "path":
                            path_value = step_output.get(field_name)
                            if path_value:
                                diff_path = str(path_value)
                                break

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
                step_index=step_index,
                total_steps=total_steps,
                parent_step_index=parent_step_index,
                parent_total_steps=parent_total_steps,
                is_hidden_step=is_hidden,
                artifacts_dir=artifacts_dir_from_marker,
                diff_path=diff_path,
                error_message=error_message,
                error_traceback=error_traceback,
                response_path=response_path,
                embedded_workflow_name=embedded_workflow_name,
                is_pre_prompt_step=is_pre_prompt_step,
                model=step.model,
                llm_provider=step.llm_provider,
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

            # The original code re-reads agent_meta.json from the step's
            # ``artifacts_dir`` field, which points to a DIFFERENT directory
            # than the parent record's artifact_dir. Fall back to the
            # filesystem helper here so the same per-step enrichment
            # behavior is preserved.
            enrich_agent_from_meta(agent, artifacts_dir_from_marker)
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
