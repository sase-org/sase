"""Workflow state loaders (filesystem) and shared timestamp-dir iteration."""

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from ....hooks.processes import is_process_running
from .._timestamps import parse_timestamp_14_digit
from ..agent import Agent, AgentType
from ..workflow import WorkflowEntry
from ._image_attachments import append_inferred_diff_images
from ._json_cache import load_json_cached
from ._meta_enrichment import enrich_agent_from_meta

ACTIVE_STATUSES = frozenset(
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

    Scans ~/.sase/projects/*/artifacts/(workflow-*|ace-run|run)/*/ once.
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
                or workflow_dir.name == "run"
            ):
                continue

            for timestamp_dir in workflow_dir.iterdir():
                if not timestamp_dir.is_dir():
                    continue
                yield project_dir, timestamp_dir


def get_workflow_timestamp_dirs() -> list[tuple[Path, Path]]:
    """Return cached list of (project_dir, timestamp_dir) pairs.

    Materializes the iterator once so multiple callers can reuse the result
    without re-traversing the filesystem.
    """
    return list(_iter_workflow_timestamp_dirs())


def load_workflow_states(
    *,
    timestamp_dirs: list[tuple[Path, Path]] | None = None,
) -> list[WorkflowEntry]:
    """Load running/completed workflows from workflow_state.json marker files.

    Scans ~/.sase/projects/*/artifacts/workflow-*/*/workflow_state.json for workflows.

    Args:
        timestamp_dirs: Pre-computed (project_dir, timestamp_dir) pairs to
            avoid re-traversing the filesystem.  When ``None``, the directory
            tree is scanned from scratch.

    Returns:
        List of WorkflowEntry objects.
    """
    from sase.xprompt import StepState, StepStatus

    entries: list[WorkflowEntry] = []

    dirs = (
        timestamp_dirs if timestamp_dirs is not None else get_workflow_timestamp_dirs()
    )
    for project_dir, timestamp_dir in dirs:
        state_file = timestamp_dir / "workflow_state.json"
        if not state_file.exists():
            continue

        try:
            data = load_json_cached(state_file)

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
                display_status in ACTIVE_STATUSES
                and pid is not None
                and not is_process_running(pid)
            ):
                # Don't mark as FAILED if any step is still in_progress.
                # The stored PID is the workflow runner process, which may have
                # died while a child subprocess (e.g., claude CLI) continues
                # executing the step.
                has_in_progress = any(s.status == StepStatus.IN_PROGRESS for s in steps)
                if not has_in_progress:
                    display_status = "FAILED"

            # Read appears_as_agent and is_anonymous flags
            appears_as_agent = data.get("appears_as_agent", False)
            is_anonymous = data.get("is_anonymous", False)

            # Extract diff_path: search backward through all steps for a
            # "diff_path" output.  Handles embedded workflows (e.g.
            # #gh + #pr) where the diff step is not the last step.
            diff_path = None
            steps_list = data.get("steps", [])
            for step_data in reversed(steps_list):
                step_out = step_data.get("output")
                if isinstance(step_out, dict) and step_out.get("diff_path"):
                    diff_path = str(step_out["diff_path"])
                    break

            # Fallback: last step's first path-typed output (for
            # workflows using a different field name for diff path).
            if not diff_path and steps_list:
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
    timestamp_dirs: list[tuple[Path, Path]] | None = None,
) -> list[Agent]:
    """Load workflow entries as Agent objects for display in Agents tab.

    Converts WorkflowEntry objects from load_workflow_states() to Agent objects
    so they can be displayed alongside other agents.

    Args:
        step_meta_by_parent: Pre-collected meta_* fields from prompt_step
            files, keyed by parent timestamp.  When provided, the expensive
            per-directory prompt_step scan is skipped (the caller already
            loaded the steps and collected meta fields).
        timestamp_dirs: Pre-computed (project_dir, timestamp_dir) pairs to
            pass through to ``load_workflow_states()``, avoiding a redundant
            filesystem traversal.

    Returns:
        List of Agent objects with agent_type=AgentType.WORKFLOW.
    """
    entries = load_workflow_states(timestamp_dirs=timestamp_dirs)
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

        # Read plan_path from plan_path.json if available in artifacts
        extra_files: list[str] = []
        if entry.artifacts_dir:
            plan_path_file = Path(entry.artifacts_dir) / "plan_path.json"
            try:
                plan_data = load_json_cached(plan_path_file)
                plan_path = plan_data.get("plan_path")
                if plan_path:
                    extra_files = [plan_path]
            except (FileNotFoundError, json.JSONDecodeError, OSError):
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
            extra_files=extra_files,
            error_message=entry.error_message,
            error_traceback=entry.error_traceback,
            step_output=step_output,
            workspace_num=workspace_num,
        )
        enrich_agent_from_meta(agent, entry.artifacts_dir)
        append_inferred_diff_images(agent)
        agents.append(agent)

    return agents
