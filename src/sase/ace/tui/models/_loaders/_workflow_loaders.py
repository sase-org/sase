"""Workflow state and step loaders."""

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from ....hooks.processes import is_process_running
from ._artifact_loaders import enrich_agent_from_meta
from .._timestamps import parse_timestamp_14_digit
from ..agent import Agent, AgentType
from ..workflow import WorkflowEntry

_ACTIVE_STATUSES = frozenset(
    {
        "RUNNING",
        "WAITING INPUT",
        "PLANNING",
        "PLAN APPROVED",
        "QUESTION",
    }
)


def _iter_workflow_timestamp_dirs() -> Iterator[tuple[Path, Path]]:
    """Yield (project_dir, timestamp_dir) for all workflow artifact directories.

    Scans ~/.sase/projects/*/artifacts/(workflow-*|ace-run)/*/ once.
    Both load_workflow_states() and load_workflow_agent_steps() use this
    shared iterator to avoid redundant directory traversal.
    """
    projects_dir = Path.home() / ".sase" / "projects"

    if not projects_dir.exists():
        return

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        artifacts_dir = project_dir / "artifacts"
        if not artifacts_dir.exists():
            continue

        for workflow_dir in artifacts_dir.iterdir():
            if not workflow_dir.is_dir():
                continue
            if not (
                workflow_dir.name.startswith("workflow-")
                or workflow_dir.name == "ace-run"
            ):
                continue

            for timestamp_dir in workflow_dir.iterdir():
                if not timestamp_dir.is_dir():
                    continue
                yield project_dir, timestamp_dir


def load_workflow_states() -> list[WorkflowEntry]:
    """Load running/completed workflows from workflow_state.json marker files.

    Scans ~/.sase/projects/*/artifacts/workflow-*/*/workflow_state.json for workflows.

    Returns:
        List of WorkflowEntry objects.
    """
    from sase.xprompt import StepState, StepStatus

    entries: list[WorkflowEntry] = []

    for project_dir, timestamp_dir in _iter_workflow_timestamp_dirs():
        state_file = timestamp_dir / "workflow_state.json"
        if not state_file.exists():
            continue

        try:
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)

            # Parse timestamp from directory name
            start_time = parse_timestamp_14_digit(timestamp_dir.name)
            if start_time is None:
                # Try ISO format from state file
                iso_time = data.get("start_time")
                if iso_time:
                    try:
                        start_time = datetime.fromisoformat(iso_time)
                    except ValueError:
                        pass

            # Map status string to display status
            status = data.get("status", "running")
            if status == "waiting_hitl":
                display_status = "WAITING INPUT"
            elif status == "completed":
                display_status = "DONE"
            elif status == "failed":
                display_status = "FAILED"
            else:
                display_status = "RUNNING"

            # Parse step states
            steps: list[StepState] = []
            for step_data in data.get("steps", []):
                step_status = StepStatus(step_data.get("status", "pending"))
                steps.append(
                    StepState(
                        name=step_data.get("name", ""),
                        status=step_status,
                        output=step_data.get("output"),
                        error=step_data.get("error"),
                    )
                )

            # Build project file path
            project_name = project_dir.name
            project_file = str(project_dir / f"{project_name}.gp")

            # Extract PID if available
            pid = data.get("pid")

            # Check PID liveness for active workflows
            if (
                display_status in _ACTIVE_STATUSES
                and pid is not None
                and not is_process_running(pid)
            ):
                display_status = "FAILED"

            # Read appears_as_agent and is_anonymous flags
            appears_as_agent = data.get("appears_as_agent", False)
            is_anonymous = data.get("is_anonymous", False)

            # Extract diff_path from the last step's first path-typed output
            diff_path = None
            steps_list = data.get("steps", [])
            if steps_list:
                last_step = steps_list[-1]
                output_types = last_step.get("output_types") or {}
                step_output = last_step.get("output")
                if output_types and isinstance(step_output, dict):
                    for field_name, field_type in output_types.items():
                        if field_type == "path":
                            path_value = step_output.get(field_name)
                            if path_value:
                                diff_path = str(path_value)
                                break

            # Fallback: check for any path-looking key in last step output
            if not diff_path and steps_list:
                last_output = steps_list[-1].get("output")
                if isinstance(last_output, dict) and last_output.get("diff_path"):
                    diff_path = str(last_output["diff_path"])

            error_message = data.get("error")
            error_traceback = data.get("traceback")
            if not error_message and display_status == "FAILED":
                for step_data in data.get("steps", []):
                    if step_data.get("status") == "failed" and step_data.get("error"):
                        error_message = (
                            f"Step '{step_data['name']}' failed: {step_data['error']}"
                        )
                        error_traceback = step_data.get("traceback")
                        break

            entries.append(
                WorkflowEntry(
                    workflow_name=data.get("workflow_name", "unknown"),
                    cl_name=data.get("context", {}).get("cl_name", "unknown"),
                    project_file=project_file,
                    status=display_status,
                    current_step=data.get("current_step_index", 0),
                    total_steps=len(steps),
                    steps=steps,
                    start_time=start_time,
                    artifacts_dir=str(timestamp_dir),
                    pid=pid,
                    appears_as_agent=appears_as_agent,
                    is_anonymous=is_anonymous,
                    diff_path=diff_path,
                    error_message=error_message,
                    error_traceback=error_traceback,
                )
            )
        except Exception:
            continue

    return entries


def load_workflow_agents(
    *,
    step_meta_by_parent: dict[str, dict[str, str]] | None = None,
) -> list[Agent]:
    """Load workflow entries as Agent objects for display in Agents tab.

    Converts WorkflowEntry objects from load_workflow_states() to Agent objects
    so they can be displayed alongside other agents.

    Args:
        step_meta_by_parent: Pre-collected meta_* fields from prompt_step
            files, keyed by parent timestamp.  When provided, the expensive
            per-directory prompt_step scan is skipped (the caller already
            loaded the steps and collected meta fields).

    Returns:
        List of Agent objects with agent_type=AgentType.WORKFLOW.
    """
    entries = load_workflow_states()
    agents: list[Agent] = []

    for entry in entries:
        # Extract timestamp from artifacts_dir path for raw_suffix
        # artifacts_dir format: ~/.sase/projects/<project>/artifacts/workflow-<name>/<timestamp>
        raw_suffix = None
        if entry.artifacts_dir:
            raw_suffix = Path(entry.artifacts_dir).name

        # Extract step_output from last completed step so that
        # appears_as_agent workflows expose meta_* fields in the TUI.
        step_output: dict[str, Any] | None = None
        if entry.steps:
            for step in reversed(entry.steps):
                if step.output and isinstance(step.output, dict):
                    step_output = step.output
                    break

        # Apply pre-collected meta_* fields from prompt steps (if available)
        if step_meta_by_parent is not None and raw_suffix:
            meta = step_meta_by_parent.get(raw_suffix)
            if meta:
                if step_output is None:
                    step_output = {}
                else:
                    # Copy to avoid mutating the WorkflowEntry's step output
                    step_output = dict(step_output)
                step_output.update(meta)

        # Extract workspace_num from step output meta_workspace
        workspace_num = None
        if step_output and step_output.get("meta_workspace"):
            try:
                workspace_num = int(step_output["meta_workspace"])
            except (ValueError, TypeError):
                pass

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
            error_message=entry.error_message,
            error_traceback=entry.error_traceback,
            step_output=step_output,
            workspace_num=workspace_num,
        )
        enrich_agent_from_meta(agent, entry.artifacts_dir)
        agents.append(agent)

    return agents


def load_workflow_agent_steps() -> tuple[list[Agent], dict[str, dict[str, str]]]:
    """Load agent step entries from workflow prompt_step_*.json marker files.

    Scans ~/.sase/projects/*/artifacts/workflow-*/*/prompt_step_*.json for agent steps.
    Also collects meta_* fields per parent timestamp so the caller can enrich
    parent workflow agents without re-reading these files.

    Returns:
        Tuple of:
        - List of Agent objects representing individual agent steps.
        - Dict mapping parent_timestamp -> {meta_key: meta_value} for parent
          workflow enrichment.
    """
    agents: list[Agent] = []
    meta_by_parent: dict[str, dict[str, str]] = {}

    for project_dir, timestamp_dir in _iter_workflow_timestamp_dirs():
        # Read parent workflow state for error propagation to child steps
        parent_wf_error: str | None = None
        parent_wf_traceback: str | None = None
        parent_wf_failed = False
        parent_state_file = timestamp_dir / "workflow_state.json"
        if parent_state_file.exists():
            try:
                with open(parent_state_file, encoding="utf-8") as f:
                    parent_state = json.load(f)
                if parent_state.get("status") == "failed":
                    parent_wf_failed = True
                    parent_wf_error = parent_state.get("error")
                    parent_wf_traceback = parent_state.get("traceback")
            except Exception:
                pass

        # Find all prompt step marker files
        for marker_file in timestamp_dir.glob("prompt_step_*.json"):
            try:
                with open(marker_file, encoding="utf-8") as f:
                    data = json.load(f)

                # Parse timestamp from directory name
                start_time = parse_timestamp_14_digit(timestamp_dir.name)

                # Build project file path
                project_name = project_dir.name
                project_file = str(project_dir / f"{project_name}.gp")

                # Map status to display string
                status = data.get("status", "completed")
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

                workflow_name = data.get("workflow_name", "unknown")
                step_name = data.get("step_name", "unknown")

                # Read new fields from marker (with backward compat defaults)
                step_type = data.get("step_type", "agent")
                step_source = data.get("step_source")
                step_output = data.get("output")
                step_index = data.get("step_index")
                total_steps = data.get("total_steps")
                parent_step_index = data.get("parent_step_index")
                parent_total_steps = data.get("parent_total_steps")
                is_hidden = data.get("hidden", False)
                is_pre_prompt_step = data.get("is_pre_prompt_step", False)
                embedded_workflow_name = data.get("embedded_workflow_name")

                # Pre-prompt steps from embedded workflows are hidden
                # by default but still loadable at FULLY_EXPANDED level.
                if is_pre_prompt_step:
                    is_hidden = True

                # Read artifacts_dir, diff_path, error, and traceback from marker
                artifacts_dir_from_marker = data.get("artifacts_dir")
                diff_path = data.get("diff_path")
                error_message = data.get("error")
                error_traceback = data.get("traceback")

                response_path = data.get("response_path")

                # Also extract diff_path from output_types if not already set
                if not diff_path:
                    output_types = data.get("output_types") or {}
                    if output_types and isinstance(step_output, dict):
                        for field_name, field_type in output_types.items():
                            if field_type == "path":
                                path_value = step_output.get(field_name)
                                if path_value:
                                    diff_path = str(path_value)
                                    break

                # Collect meta_* fields for parent workflow enrichment
                if isinstance(step_output, dict):
                    ts_name = timestamp_dir.name
                    for k, v in step_output.items():
                        if k.startswith("meta_") and v:
                            if ts_name not in meta_by_parent:
                                meta_by_parent[ts_name] = {}
                            meta_by_parent[ts_name][k] = str(v)

                agent = Agent(
                    agent_type=AgentType.WORKFLOW,
                    cl_name=step_name,
                    project_file=project_file,
                    status=display_status,
                    start_time=start_time,
                    workflow=workflow_name,
                    raw_suffix=timestamp_dir.name,
                    parent_workflow=workflow_name,
                    parent_timestamp=timestamp_dir.name,
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
                )
                # If step is still RUNNING but parent workflow failed,
                # mark step as FAILED and propagate the workflow error
                if (
                    parent_wf_failed
                    and agent.status == "RUNNING"
                    and not agent.error_message
                ):
                    agent.status = "FAILED"
                    agent.error_message = parent_wf_error
                    agent.error_traceback = parent_wf_traceback

                enrich_agent_from_meta(agent, artifacts_dir_from_marker)
                agents.append(agent)
            except Exception:
                continue

    return agents, meta_by_parent
