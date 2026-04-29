"""Workflow agent-step loaders (filesystem prompt_step_*.json markers)."""

from pathlib import Path

from .._timestamps import parse_timestamp_14_digit
from ..agent import Agent, AgentType
from ._json_cache import get_loader_executor, load_json_cached
from ._meta_enrichment import enrich_agent_from_meta
from ._workflow_loaders import get_workflow_timestamp_dirs


def _load_workflow_agent_steps_for_dir(
    project_dir: Path,
    timestamp_dir: Path,
) -> tuple[list[Agent], dict[str, str]]:
    """Load agent steps and collect meta_* fields for a single timestamp dir.

    Returns:
        Tuple of (agents_for_dir, meta_dict_for_parent_timestamp).
        The meta dict is keyed on meta_key -> meta_value; callers attach it
        to ``meta_by_parent[timestamp_dir.name]``.
    """
    dir_agents: list[Agent] = []
    dir_meta: dict[str, str] = {}

    # Read parent workflow state for status propagation to child steps
    parent_wf_error: str | None = None
    parent_wf_traceback: str | None = None
    parent_wf_failed = False
    parent_wf_completed = False
    parent_state_file = timestamp_dir / "workflow_state.json"
    if parent_state_file.exists():
        try:
            parent_state = load_json_cached(parent_state_file)
            parent_status = parent_state.get("status")
            if parent_status == "failed":
                parent_wf_failed = True
                parent_wf_error = parent_state.get("error")
                parent_wf_traceback = parent_state.get("traceback")
            elif parent_status == "completed":
                parent_wf_completed = True
        except Exception:
            pass

    # Find all prompt step marker files
    for marker_file in timestamp_dir.glob("prompt_step_*.json"):
        try:
            data = load_json_cached(marker_file)

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
                model=data.get("model"),
                llm_provider=data.get("llm_provider"),
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

            # If step is still RUNNING but parent workflow completed,
            # mark step as DONE (e.g. planner agent killed by sase plan)
            if parent_wf_completed and agent.status == "RUNNING":
                agent.status = "DONE"

            enrich_agent_from_meta(agent, artifacts_dir_from_marker)
            dir_agents.append(agent)
        except Exception:
            continue

    return dir_agents, dir_meta


def load_workflow_agent_steps(
    *,
    timestamp_dirs: list[tuple[Path, Path]] | None = None,
) -> tuple[list[Agent], dict[str, dict[str, str]]]:
    """Load agent step entries from workflow prompt_step_*.json marker files.

    Scans ~/.sase/projects/*/artifacts/workflow-*/*/prompt_step_*.json for agent steps.
    Also collects meta_* fields per parent timestamp so the caller can enrich
    parent workflow agents without re-reading these files.

    Args:
        timestamp_dirs: Pre-computed (project_dir, timestamp_dir) pairs to
            avoid re-traversing the filesystem.

    Returns:
        Tuple of:
        - List of Agent objects representing individual agent steps.
        - Dict mapping parent_timestamp -> {meta_key: meta_value} for parent
          workflow enrichment.
    """
    dirs = (
        timestamp_dirs if timestamp_dirs is not None else get_workflow_timestamp_dirs()
    )
    if not dirs:
        return [], {}

    executor = get_loader_executor()
    results = list(
        executor.map(
            lambda pair: _load_workflow_agent_steps_for_dir(pair[0], pair[1]),
            dirs,
        )
    )

    agents: list[Agent] = []
    meta_by_parent: dict[str, dict[str, str]] = {}
    for pair, (dir_agents, dir_meta) in zip(dirs, results, strict=True):
        agents.extend(dir_agents)
        if dir_meta:
            meta_by_parent[pair[1].name] = dir_meta

    return agents, meta_by_parent
